"""
动态代理池管理

- 支持多种代理来源（免费/付费API/自建）
- 自动健康检查和淘汰
- 按平台分配最优代理
"""
import asyncio
import time
import random
from dataclasses import dataclass, field
from typing import Optional
import httpx
from loguru import logger
from config.settings import settings


@dataclass
class ProxyInfo:
    """代理信息"""
    url: str                          # http://ip:port 或 socks5://ip:port
    source: str = "manual"            # 来源标识
    success_count: int = 0
    fail_count: int = 0
    total_latency: float = 0.0
    last_check: float = 0
    last_used: float = 0
    is_alive: bool = True
    blocked_platforms: set = field(default_factory=set)  # 被哪些平台封了

    @property
    def avg_latency(self) -> float:
        total = self.success_count + self.fail_count
        return self.total_latency / max(total, 1)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / max(total, 1)

    @property
    def score(self) -> float:
        """综合评分（用于排序选择）"""
        rate = self.success_rate
        latency_score = max(0, 1 - self.avg_latency / 10)
        return rate * 0.7 + latency_score * 0.3


class ProxyPool:
    """
    代理池管理器

    使用方式:
        pool = ProxyPool()
        proxy = await pool.get_proxy("taobao")
        # 使用 proxy.url 发起请求
        pool.report_success(proxy)  # 或 report_fail(proxy, "taobao")
    """

    # 免费代理源（纯文本格式，每行一个 ip:port）
    FREE_PROXY_SOURCES = [
        # Proxifly - GitHub 维护，每5分钟更新
        "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
        # TheSpeedX - GitHub 维护
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        # monosans - GitHub 维护
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    ]

    def __init__(self):
        self._proxies: list[ProxyInfo] = []
        self._lock = asyncio.Lock()
        self._enabled = False  # 初始化后根据实际数量决定

    @property
    def enabled(self) -> bool:
        return self._enabled and len(self._proxies) > 0

    @property
    def size(self) -> int:
        return len([p for p in self._proxies if p.is_alive])

    async def initialize(self):
        """初始化代理池"""
        # 1. 从配置加载静态代理
        static_proxies = getattr(settings, 'PROXY_LIST', None)
        if static_proxies:
            for url in static_proxies.split(','):
                url = url.strip()
                if url:
                    self._proxies.append(ProxyInfo(url=url, source="static"))

        # 2. 从付费API获取代理
        await self._fetch_from_api()

        # 3. 从免费源抓取公共代理
        await self._fetch_free_proxies()

        # 4. 验证代理可用性（快速检查前20个）
        if self._proxies:
            await self._quick_validate(max_check=20)

        validated_alive = len([p for p in self._proxies if p.is_alive and p.last_check > 0])
        validated_total = len([p for p in self._proxies if p.last_check > 0])

        if validated_total > 0 and validated_alive == 0:
            # 验证全部失败 → 标记所有未验证代理为死亡，禁用代理池
            for p in self._proxies:
                if p.last_check == 0:
                    p.is_alive = False
            self._enabled = False
            logger.warning(f"[代理池] 验证 {validated_total} 个代理全部失败，禁用代理池（使用直连）")
        else:
            alive = len([p for p in self._proxies if p.is_alive])
            self._enabled = alive > 0
            logger.info(f"[代理池] 初始化完成，共 {alive} 个可用代理（已验证 {validated_alive}/{validated_total}）")

    async def _fetch_from_api(self):
        """
        从代理API获取代理

        ========================================
        代理API接口预留位置
        ========================================
        支持的付费代理服务商（在 .env 中配置）：

        1. 快代理:
           PROXY_API_URL=https://dps.kdlapi.com/api/getdps/?orderid=xxx&num=10&format=json

        2. 芝麻代理:
           PROXY_API_URL=https://h.zhimaruanjian.com/getip?num=10&type=2&pro=0&city=0

        3. 站大爷:
           PROXY_API_URL=https://www.zdaye.com/api/?api=xxx&num=10&type=2

        4. 自建代理池 API:
           PROXY_API_URL=http://your-proxy-pool:5010/get_all/

        配置示例(.env):
           PROXY_API_URL=https://your-proxy-api.com/get?num=20&format=json
           PROXY_API_KEY=your-api-key
        ========================================
        """
        api_url = getattr(settings, 'PROXY_API_URL', None)
        if not api_url:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {}
                api_key = getattr(settings, 'PROXY_API_KEY', None)
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                resp = await client.get(api_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                # 根据API返回格式解析代理列表
                # >>> 根据你使用的代理服务商调整解析逻辑 <<<
                proxy_list = []
                if isinstance(data, list):
                    proxy_list = data
                elif isinstance(data, dict):
                    proxy_list = data.get("data", data.get("proxies", data.get("list", [])))

                for item in proxy_list:
                    if isinstance(item, str):
                        url = item if "://" in item else f"http://{item}"
                    elif isinstance(item, dict):
                        ip = item.get("ip", item.get("host", ""))
                        port = item.get("port", "")
                        url = f"http://{ip}:{port}"
                    else:
                        continue

                    if url and url not in {p.url for p in self._proxies}:
                        self._proxies.append(ProxyInfo(url=url, source="api"))

                logger.info(f"[代理池] 从API获取了 {len(proxy_list)} 个代理")
        except Exception as e:
            logger.warning(f"[代理池] 从API获取代理失败: {e}")

    async def _fetch_free_proxies(self):
        """从 GitHub 免费代理源抓取代理列表"""
        existing_urls = {p.url for p in self._proxies}
        added = 0

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for source_url in self.FREE_PROXY_SOURCES:
                try:
                    resp = await client.get(source_url)
                    resp.raise_for_status()
                    lines = resp.text.strip().splitlines()

                    for line in lines:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # 格式: ip:port 或 http://ip:port
                        url = line if "://" in line else f"http://{line}"
                        if url not in existing_urls:
                            self._proxies.append(ProxyInfo(url=url, source="free"))
                            existing_urls.add(url)
                            added += 1

                    logger.debug(f"[代理池] 从 {source_url.split('/')[-2]} 获取代理成功")
                except Exception as e:
                    logger.warning(f"[代理池] 免费源抓取失败 {source_url[:60]}...: {e}")

        logger.info(f"[代理池] 从免费源共获取 {added} 个代理")

    async def _quick_validate(self, max_check: int = 20):
        """快速验证前 N 个代理的可用性"""
        check_url = "https://httpbin.org/ip"
        to_check = [p for p in self._proxies if p.is_alive][:max_check]

        if not to_check:
            return

        async def _validate_one(proxy: ProxyInfo):
            try:
                start = time.time()
                async with httpx.AsyncClient(
                    proxies=proxy.url, timeout=8, follow_redirects=True
                ) as client:
                    resp = await client.get(check_url)
                    resp.raise_for_status()
                latency = time.time() - start
                proxy.total_latency += latency
                proxy.success_count += 1
                proxy.last_check = time.time()
                proxy.is_alive = True
            except Exception:
                proxy.is_alive = False
                proxy.last_check = time.time()

        await asyncio.gather(
            *[_validate_one(p) for p in to_check],
            return_exceptions=True,
        )

        alive = len([p for p in to_check if p.is_alive])
        logger.info(f"[代理池] 快速验证完成: {alive}/{len(to_check)} 个存活")

    async def get_proxy(self, platform: str = "") -> Optional[ProxyInfo]:
        """
        获取最优代理

        优先返回：成功率高、延迟低、未被该平台封锁的代理
        """
        async with self._lock:
            candidates = [
                p for p in self._proxies
                if p.is_alive and platform not in p.blocked_platforms
            ]

            if not candidates:
                # 尝试刷新代理池
                await self._fetch_from_api()
                candidates = [p for p in self._proxies if p.is_alive]

            if not candidates:
                return None

            # 按评分排序，取前30%中随机一个（避免集中使用同一个代理）
            candidates.sort(key=lambda p: p.score, reverse=True)
            top_n = max(1, len(candidates) // 3)
            proxy = random.choice(candidates[:top_n])
            proxy.last_used = time.time()
            return proxy

    def report_success(self, proxy: ProxyInfo, latency: float = 0):
        """报告代理请求成功"""
        proxy.success_count += 1
        proxy.total_latency += latency
        proxy.is_alive = True

    def report_fail(self, proxy: ProxyInfo, platform: str = "", is_blocked: bool = False):
        """报告代理请求失败"""
        proxy.fail_count += 1
        if is_blocked and platform:
            proxy.blocked_platforms.add(platform)

        # 成功率过低则标记为死亡
        total = proxy.success_count + proxy.fail_count
        if total >= 5 and proxy.success_rate < 0.2:
            proxy.is_alive = False
            logger.debug(f"[代理池] 淘汰代理 {proxy.url} (成功率 {proxy.success_rate:.0%})")

    async def health_check(self):
        """批量健康检查"""
        check_url = "https://httpbin.org/ip"
        tasks = []
        for proxy in self._proxies:
            if not proxy.is_alive and time.time() - proxy.last_check < 300:
                continue
            tasks.append(self._check_one(proxy, check_url))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        alive = len([p for p in self._proxies if p.is_alive])
        logger.info(f"[代理池] 健康检查完成，存活 {alive}/{len(self._proxies)}")

    async def _check_one(self, proxy: ProxyInfo, check_url: str):
        """检查单个代理"""
        try:
            start = time.time()
            async with httpx.AsyncClient(proxies=proxy.url, timeout=8) as client:
                resp = await client.get(check_url)
                resp.raise_for_status()
            latency = time.time() - start
            proxy.is_alive = True
            proxy.total_latency += latency
            proxy.last_check = time.time()
        except Exception:
            proxy.is_alive = False
            proxy.last_check = time.time()

    def get_stats(self) -> dict:
        alive = [p for p in self._proxies if p.is_alive]
        return {
            "total": len(self._proxies),
            "alive": len(alive),
            "avg_success_rate": round(sum(p.success_rate for p in alive) / max(len(alive), 1) * 100, 1),
            "avg_latency": round(sum(p.avg_latency for p in alive) / max(len(alive), 1), 2),
            "sources": dict(
                sorted(
                    {s: len([p for p in self._proxies if p.source == s]) for s in {p.source for p in self._proxies}}.items()
                )
            ),
        }

    def add_proxy(self, url: str, source: str = "manual"):
        """手动添加代理"""
        if url not in {p.url for p in self._proxies}:
            self._proxies.append(ProxyInfo(url=url, source=source))
