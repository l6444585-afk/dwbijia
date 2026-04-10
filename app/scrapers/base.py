"""
爬虫基类 - 所有平台爬虫的基础类
遵守robots协议，控制爬取频率
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger
from config.settings import settings


class BaseScraper(ABC):
    """爬虫基类"""

    def __init__(self):
        self.platform: str = ""
        self.delay: float = settings.CRAWL_DELAY
        self.max_requests_per_hour: int = settings.MAX_REQUESTS_PER_HOUR
        self._request_count: int = 0
        self._hour_start: float = time.time()
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    async def _rate_limit(self):
        """速率控制 - 遵守爬取频率限制"""
        now = time.time()
        # 每小时重置计数
        if now - self._hour_start > 3600:
            self._request_count = 0
            self._hour_start = now

        if self._request_count >= self.max_requests_per_hour:
            wait = 3600 - (now - self._hour_start)
            logger.warning(f"[{self.platform}] 达到每小时请求上限，等待 {wait:.0f}s")
            await asyncio.sleep(wait)
            self._request_count = 0
            self._hour_start = time.time()

        self._request_count += 1
        await asyncio.sleep(self.delay)

    @abstractmethod
    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """搜索商品"""
        pass

    @abstractmethod
    async def get_detail(self, product_id: str) -> Optional[dict]:
        """获取商品详情"""
        pass

    @abstractmethod
    async def get_price(self, product_id: str) -> Optional[float]:
        """获取商品当前价格"""
        pass
