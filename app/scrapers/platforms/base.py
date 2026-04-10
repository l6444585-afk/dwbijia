"""
增强型爬虫基类

特点：
- HTTP 优先，浏览器渲染兜底
- 自动重试 + 策略切换
- 内置反爬检测与应对
- 数据质量校验
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

import httpx

from app.scrapers.engine.rate_limiter import AdaptiveRateLimiter
from app.scrapers.engine.proxy_pool import ProxyPool
from app.scrapers.engine.fingerprint import FingerprintGenerator, BrowserFingerprint
from app.scrapers.engine.browser import BrowserPool, simulate_human, HAS_PLAYWRIGHT
from app.scrapers.engine.anti_detect import AntiDetectEngine, BlockType, Strategy
from app.scrapers.engine.cookie_manager import CookieManager


# 全局共享引擎实例
_rate_limiter = AdaptiveRateLimiter()
_proxy_pool = ProxyPool()
_browser_pool = BrowserPool(max_contexts=5)
_anti_detect = AntiDetectEngine()
_cookie_manager = CookieManager()


class RealBaseScraper(ABC):
    """
    真实数据爬虫基类

    子类只需实现:
    - platform: 平台标识
    - _parse_search_html(): 从HTML解析搜索结果
    - _parse_detail_html(): 从HTML解析商品详情
    - _get_search_url(): 搜索页URL
    - _get_detail_url(): 详情页URL
    - 可选: _try_api_search(), _try_api_detail() 用于直接API调用
    """

    platform: str = ""
    max_retries: int = 3

    def __init__(self):
        self.rate_limiter = _rate_limiter
        self.proxy_pool = _proxy_pool
        self.browser_pool = _browser_pool
        self.anti_detect = _anti_detect
        self.cookie_manager = _cookie_manager
        self.fp_gen = FingerprintGenerator()
        # 统计
        self._stats = {
            "total_requests": 0,
            "success": 0,
            "failed": 0,
            "browser_fallbacks": 0,
        }

    # ===== 子类必须实现 =====

    @abstractmethod
    def _get_search_url(self, keyword: str, page: int) -> str:
        """返回搜索页URL"""
        pass

    @abstractmethod
    def _get_detail_url(self, product_id: str) -> str:
        """返回商品详情页URL"""
        pass

    @abstractmethod
    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:
        """从HTML中解析商品列表"""
        pass

    @abstractmethod
    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """从HTML中解析商品详情"""
        pass

    # ===== 子类可选实现（直接API调用） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:  # noqa: ARG002
        """尝试通过API搜索（更快，无需渲染）- 子类覆盖此方法"""
        return None

    async def _try_api_detail(self, product_id: str) -> Optional[dict]:  # noqa: ARG002
        """尝试通过API获取详情 - 子类覆盖此方法"""
        return None

    # ===== 公共接口 =====

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """搜索商品 - 自动选择最优获取方式"""
        self._stats["total_requests"] += 1

        # 策略1: 优先尝试直接API调用
        api_result = await self._try_api_search(keyword, page)
        if api_result:
            self._stats["success"] += 1
            return {"items": api_result[:page_size], "total": len(api_result), "platform": self.platform, "source": "api"}

        # 策略2: HTTP请求 + HTML解析
        url = self._get_search_url(keyword, page)
        html = await self._fetch_with_retry(url)
        if html:
            items = self._parse_search_html(html, keyword)
            if items:
                self._stats["success"] += 1
                return {"items": items[:page_size], "total": len(items), "platform": self.platform, "source": "http"}

        # 策略3: 浏览器渲染兜底
        if HAS_PLAYWRIGHT:
            self._stats["browser_fallbacks"] += 1
            html = await self._fetch_with_browser(url)
            if html:
                items = self._parse_search_html(html, keyword)
                if items:
                    self._stats["success"] += 1
                    return {"items": items[:page_size], "total": len(items), "platform": self.platform, "source": "browser"}

        self._stats["failed"] += 1
        logger.warning(f"[{self.platform}] 搜索失败: {keyword}")
        return {"items": [], "total": 0, "platform": self.platform, "source": "failed"}

    async def get_detail(self, product_id: str) -> Optional[dict]:
        """获取商品详情"""
        self._stats["total_requests"] += 1

        # API优先
        api_result = await self._try_api_detail(product_id)
        if api_result:
            self._stats["success"] += 1
            return api_result

        # HTTP请求
        url = self._get_detail_url(product_id)
        html = await self._fetch_with_retry(url)
        if html:
            detail = self._parse_detail_html(html, product_id)
            if detail:
                self._stats["success"] += 1
                return detail

        # 浏览器兜底
        if HAS_PLAYWRIGHT:
            self._stats["browser_fallbacks"] += 1
            html = await self._fetch_with_browser(url)
            if html:
                detail = self._parse_detail_html(html, product_id)
                if detail:
                    self._stats["success"] += 1
                    return detail

        self._stats["failed"] += 1
        return None

    async def get_price(self, product_id: str) -> Optional[float]:
        """获取当前价格"""
        detail = await self.get_detail(product_id)
        return detail.get("price") if detail else None

    # ===== HTTP 请求 =====

    async def _fetch_with_retry(self, url: str) -> Optional[str]:
        """
        带自动重试和反爬应对的HTTP请求

        流程: 请求 → 检测反爬 → 选择策略 → 重试
        """
        fingerprint = self.fp_gen.generate(mobile=True)
        # 从本地浏览器提取当前平台的 Cookie
        platform_cookies = self.cookie_manager.get_cookies(self.platform)

        for attempt in range(self.max_retries):
            # 速率控制
            if not await self.rate_limiter.acquire(self.platform):
                continue

            # 获取代理（最后一次重试用直连兜底）
            use_proxy = self.proxy_pool.enabled and attempt < self.max_retries - 1
            proxy_info = await self.proxy_pool.get_proxy(self.platform) if use_proxy else None
            proxy_url = proxy_info.url if proxy_info else None

            try:
                start = time.time()
                client_kwargs = {"timeout": 10 if proxy_url else 15, "follow_redirects": True}
                if proxy_url:
                    client_kwargs["proxies"] = proxy_url
                # 注入浏览器 Cookie
                if platform_cookies:
                    client_kwargs["cookies"] = platform_cookies
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.get(url, headers=fingerprint.headers)
                    latency = time.time() - start
                    body = resp.text

                # 检测反爬
                detection = self.anti_detect.detect(
                    status_code=resp.status_code,
                    body=body,
                    url=url,
                    headers=dict(resp.headers),
                )

                if resp.status_code == 200 and detection.block_type == BlockType.NONE:
                    # 正常响应
                    self.rate_limiter.report_success(self.platform)
                    if proxy_info:
                        self.proxy_pool.report_success(proxy_info, latency)
                    return body

                if resp.status_code == 200 and detection.block_type != BlockType.NONE:
                    # 200 但页面包含反爬特征（验证码/JS挑战等）
                    logger.info(
                        f"[{self.platform}] 页面反爬 [{detection.block_type.value}]: "
                        f"{detection.detail} (尝试 {attempt + 1}/{self.max_retries})"
                    )
                    self.rate_limiter.report_blocked(self.platform)
                    if proxy_info:
                        self.proxy_pool.report_fail(proxy_info, self.platform, is_blocked=True)
                else:
                    # 非200状态码 - 普通错误，不计入反爬
                    logger.debug(
                        f"[{self.platform}] HTTP {resp.status_code} "
                        f"(尝试 {attempt + 1}/{self.max_retries})"
                    )
                    self.rate_limiter.report_error(self.platform)
                    if proxy_info:
                        self.proxy_pool.report_fail(proxy_info, self.platform)

                # 执行应对策略
                strategy = self.anti_detect.recommend_strategy(self.platform, detection.block_type)
                await self._execute_strategy(strategy, fingerprint)

            except httpx.TimeoutException:
                logger.debug(f"[{self.platform}] 请求超时 (尝试 {attempt + 1})")
                self.rate_limiter.report_error(self.platform)
                if proxy_info:
                    self.proxy_pool.report_fail(proxy_info, self.platform)
            except Exception as e:
                logger.debug(f"[{self.platform}] 请求异常: {e} (尝试 {attempt + 1})")
                self.rate_limiter.report_error(self.platform)

            # 更换指纹重试
            fingerprint = self.fp_gen.generate(mobile=True)

        return None

    async def _execute_strategy(self, strategy: Strategy, fingerprint: BrowserFingerprint):  # noqa: ARG002
        """执行反爬应对策略"""
        if strategy == Strategy.RETRY_DELAY:
            await asyncio.sleep(3)
        elif strategy == Strategy.BACKOFF:
            await asyncio.sleep(10)
        elif strategy == Strategy.SWITCH_PROXY:
            pass  # 下次循环自动获取新代理
        elif strategy in (Strategy.SWITCH_UA, Strategy.ROTATE_FINGERPRINT):
            pass  # 下次循环自动生成新指纹
        elif strategy == Strategy.USE_BROWSER:
            pass  # 外层会尝试浏览器兜底

    # ===== 浏览器渲染 =====

    async def _fetch_with_browser(self, url: str) -> Optional[str]:
        """使用 Playwright 浏览器获取页面"""
        if not HAS_PLAYWRIGHT:
            return None

        fingerprint = self.fp_gen.generate(mobile=True)
        proxy_info = await self.proxy_pool.get_proxy(self.platform) if self.proxy_pool.enabled else None
        proxy_url = proxy_info.url if proxy_info else None

        context = None
        page = None
        try:
            context = await self.browser_pool.get_context(fingerprint=fingerprint, proxy=proxy_url)
            if not context:
                return None

            # 注入浏览器 Cookie 到 Playwright 上下文
            pw_cookies = self.cookie_manager.get_playwright_cookies(self.platform)
            if pw_cookies:
                await context.add_cookies(pw_cookies)

            page = await context.new_page()

            # 拦截不必要的资源加载（提速）
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}", lambda route: route.abort())

            # 导航
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)

            # 模拟人类行为
            await simulate_human(page, scroll=True)

            # 等待关键内容加载
            await self._wait_for_content(page)

            html = await page.content()
            return html

        except Exception as e:
            logger.warning(f"[{self.platform}] 浏览器获取失败: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                await self.browser_pool.close_context(context)

    async def _wait_for_content(self, page):
        """等待页面关键内容加载 - 子类可覆盖"""
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            await asyncio.sleep(2)

    # ===== 统计 =====

    def get_stats(self) -> dict:
        total = max(self._stats["total_requests"], 1)
        return {
            "platform": self.platform,
            **self._stats,
            "success_rate": round(self._stats["success"] / total * 100, 1),
            "browser_fallback_rate": round(self._stats["browser_fallbacks"] / total * 100, 1),
            "rate_limiter": self.rate_limiter.get_stats(self.platform),
        }
