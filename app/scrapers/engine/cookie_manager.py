"""
浏览器 Cookie 提取与管理模块

功能：
- 从本地浏览器（Chrome、Safari）只读提取 Cookie
- 按平台域名过滤
- 缓存机制，避免频繁读取
- 提供 dict 和 header 字符串两种格式

安全：绝不会关闭、重启或干扰用户的浏览器进程
"""
import time
from typing import Optional

from loguru import logger

# 尝试导入 browser-cookie3，不可用时回退到 browser_cookie
_cookie_lib = None
_cookie_lib_name: Optional[str] = None

try:
    import browser_cookie3 as _cookie_lib  # type: ignore[no-redef]
    _cookie_lib_name = "browser_cookie3"
except ImportError:
    try:
        import browser_cookie as _cookie_lib  # type: ignore[no-redef]
        _cookie_lib_name = "browser_cookie"
    except ImportError:
        logger.warning(
            "[CookieManager] browser-cookie3 和 browser_cookie 均未安装，"
            "Cookie 提取功能不可用。运行: pip install browser-cookie3"
        )

# 各平台对应的 Cookie 域名
PLATFORM_DOMAINS: dict[str, list[str]] = {
    "taobao": [".taobao.com", ".tmall.com"],
    "dewu": [".dewu.com", ".poizon.com"],
    "jd": [".jd.com", ".jd.hk"],
    "pdd": [".yangkeduo.com", ".pinduoduo.com"],
    "1688": [".1688.com", ".alibaba.com"],
    "shihuo": [".shihuo.com"],
}


def _domain_matches(cookie_domain: str, target_domain: str) -> bool:
    """判断 cookie 域名是否匹配目标域名（支持子域名匹配）"""
    cookie_domain = cookie_domain.lstrip(".")
    target_domain = target_domain.lstrip(".")
    return cookie_domain == target_domain or cookie_domain.endswith(f".{target_domain}")


def _extract_from_browser(domains: list[str]) -> dict[str, str]:
    """
    从本地浏览器只读提取指定域名的 Cookie

    依次尝试 Chrome → Safari，绝不关闭或重启浏览器进程。
    """
    if _cookie_lib is None:
        return {}

    cookies: dict[str, str] = {}
    # 按优先级尝试不同浏览器
    browser_loaders = [
        ("Chrome", getattr(_cookie_lib, "chrome", None)),
        ("Safari", getattr(_cookie_lib, "safari", None)),
    ]

    for browser_name, loader in browser_loaders:
        if loader is None:
            continue
        try:
            jar = loader(domain_name="")
            for cookie in jar:
                for target_domain in domains:
                    if _domain_matches(cookie.domain, target_domain):
                        cookies[cookie.name] = cookie.value
                        break
            if cookies:
                logger.debug(f"[CookieManager] 从 {browser_name} 提取到 {len(cookies)} 个 Cookie")
                return cookies
        except PermissionError:
            logger.debug(f"[CookieManager] {browser_name} Cookie 数据库被锁定，跳过")
        except Exception as e:
            logger.debug(f"[CookieManager] 从 {browser_name} 提取失败: {e}")

    return cookies


class CookieManager:
    """
    Cookie 管理器

    从用户本地浏览器只读提取 Cookie，按平台缓存，支持自动过期。
    绝不会关闭、重启或干扰用户浏览器。
    """

    def __init__(self, cache_ttl: int = 1800):
        """
        初始化 Cookie 管理器

        Args:
            cache_ttl: 缓存有效期（秒），默认 30 分钟
        """
        self._cache: dict[str, dict[str, str]] = {}
        self._cache_ts: dict[str, float] = {}
        self._cache_ttl = cache_ttl

    def _is_cache_valid(self, platform: str) -> bool:
        """检查缓存是否有效"""
        if platform not in self._cache_ts:
            return False
        return (time.time() - self._cache_ts[platform]) < self._cache_ttl

    def _load_cookies(self, platform: str) -> dict[str, str]:
        """从浏览器加载指定平台的 Cookie 并缓存"""
        domains = PLATFORM_DOMAINS.get(platform, [])
        if not domains:
            logger.debug(f"[CookieManager] 未知平台: {platform}，无对应域名配置")
            return {}

        cookies = _extract_from_browser(domains)
        # 即使为空也缓存，避免频繁读取浏览器数据库
        self._cache[platform] = cookies
        self._cache_ts[platform] = time.time()

        if cookies:
            logger.debug(f"[CookieManager] {platform} 缓存了 {len(cookies)} 个 Cookie")
        else:
            logger.debug(f"[CookieManager] {platform} 未提取到 Cookie")
        return cookies

    def get_cookies(self, platform: str) -> dict[str, str]:
        """
        获取指定平台的 Cookie（dict 格式，适用于 httpx）

        Args:
            platform: 平台标识（taobao/dewu/jd/pdd/1688/shihuo）

        Returns:
            Cookie 键值对字典，无可用 Cookie 时返回空字典
        """
        if self._is_cache_valid(platform):
            return self._cache.get(platform, {})
        return self._load_cookies(platform)

    def get_cookie_header(self, platform: str) -> str:
        """
        获取指定平台的 Cookie 字符串（适用于 HTTP Cookie 请求头）

        Args:
            platform: 平台标识

        Returns:
            格式如 "key1=value1; key2=value2"，无 Cookie 时返回空字符串
        """
        cookies = self.get_cookies(platform)
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    def refresh(self, platform: str) -> None:
        """强制刷新指定平台的 Cookie 缓存"""
        self._cache.pop(platform, None)
        self._cache_ts.pop(platform, None)
        self._load_cookies(platform)
        logger.info(f"[CookieManager] 已刷新 {platform} 的 Cookie")

    def has_cookies(self, platform: str) -> bool:
        """检查指定平台是否有可用的 Cookie"""
        return bool(self.get_cookies(platform))

    def get_playwright_cookies(self, platform: str) -> list[dict]:
        """
        获取 Playwright 格式的 Cookie 列表（用于注入浏览器上下文）

        Returns:
            Playwright add_cookies 所需的 dict 列表
        """
        cookies = self.get_cookies(platform)
        domains = PLATFORM_DOMAINS.get(platform, [])
        # 使用第一个域名作为默认域
        domain = domains[0] if domains else ""

        return [
            {"name": name, "value": value, "domain": domain, "path": "/"}
            for name, value in cookies.items()
        ]
