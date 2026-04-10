"""
爬虫 SDK 客户端

提供统一的接口供比价系统调用

使用方式:
    from app.scrapers.sdk.client import ScraperClient

    client = ScraperClient()
    await client.initialize()

    # 搜索并比价
    result = await client.search("Nike Air Force 1")

    # 获取商品详情
    detail = await client.get_detail("taobao", "123456")

    # 批量查询价格
    prices = await client.batch_get_prices([
        ("taobao", "id1"), ("dewu", "id2"), ...
    ])

    # 查看系统状态
    status = client.get_system_status()
"""
import asyncio
from typing import Optional
from loguru import logger

from app.scrapers.platforms.taobao_real import TaobaoRealScraper
from app.scrapers.platforms.dewu_real import DewuRealScraper
from app.scrapers.platforms.shihuo_real import ShihuoRealScraper
from app.scrapers.platforms.jd_real import JdRealScraper
from app.scrapers.platforms.ali1688_real import Ali1688RealScraper
from app.scrapers.platforms.pdd_real import PddRealScraper
from app.scrapers.platforms.base import _proxy_pool, _browser_pool
from app.scrapers.monitor.health import HealthMonitor
from app.scrapers.monitor.quality import DataQualityChecker
from app.scrapers.queue.task_queue import ScraperTaskQueue, ScraperTask, TaskPriority


class ScraperClient:
    """
    爬虫SDK统一客户端

    封装所有平台爬虫，提供:
    - 统一的搜索/详情/价格接口
    - 数据质量检查
    - 健康监控
    - 批量并发支持
    """

    def __init__(self):
        self.scrapers = {
            "taobao": TaobaoRealScraper(),
            "dewu": DewuRealScraper(),
            "shihuo": ShihuoRealScraper(),
            "jd": JdRealScraper(),
            "1688": Ali1688RealScraper(),
            "pdd": PddRealScraper(),
        }
        self.health = HealthMonitor()
        self.quality = DataQualityChecker()
        self.queue = ScraperTaskQueue(max_concurrent=10)
        self._initialized = False

    async def initialize(self):
        """初始化SDK（代理池、浏览器池等）"""
        if self._initialized:
            return
        await _proxy_pool.initialize()
        # 浏览器池延迟初始化（首次使用时自动启动）
        self._initialized = True
        logger.info("[SDK] 爬虫客户端初始化完成")

    async def shutdown(self):
        """关闭SDK"""
        await _browser_pool.shutdown()
        self._initialized = False
        logger.info("[SDK] 爬虫客户端已关闭")

    # ===== 搜索 =====

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """
        搜索并比价（同时搜索所有平台）

        Returns:
            {
                "keyword": str,
                "platforms": {
                    "taobao": {"items": [...], "total": n, "source": "api|http|browser"},
                    "dewu": {"items": [...], "total": n, "source": "api|http|browser"},
                },
                "all_items": [...],
                "quality": {"valid": n, "invalid": n},
            }
        """
        await self.initialize()

        # 并发搜索所有平台
        tasks = {}
        for name, scraper in self.scrapers.items():
            if self.health.is_healthy(name) or self.health.should_retry(name):
                tasks[name] = scraper.search(keyword, page, page_size)

        results = {}
        for name, coro in tasks.items():
            try:
                result = await coro
                results[name] = result
                if result.get("items"):
                    self.health.report_success(name)
                else:
                    self.health.report_failure(name, "搜索返回空结果")
            except Exception as e:
                self.health.report_failure(name, str(e))
                results[name] = {"items": [], "total": 0, "platform": name, "source": "error"}

        # 数据质量检查
        all_items = []
        for name, result in results.items():
            qc = self.quality.check_batch(result.get("items", []))
            result["items"] = qc["valid_items"]
            result["quality"] = qc["summary"]
            all_items.extend(qc["valid_items"])

        return {
            "keyword": keyword,
            "platforms": results,
            "all_items": all_items,
            "total_items": len(all_items),
        }

    # ===== 详情 =====

    async def get_detail(self, platform: str, product_id: str) -> Optional[dict]:
        """获取商品详情"""
        await self.initialize()

        scraper = self.scrapers.get(platform)
        if not scraper:
            return None

        try:
            detail = await scraper.get_detail(product_id)
            if detail:
                qc = self.quality.check(detail)
                if qc["valid"]:
                    self.health.report_success(platform)
                    return detail
                else:
                    logger.warning(f"[SDK] 详情数据质量问题: {qc['issues']}")
                    self.health.report_success(platform)
                    return detail  # 仍然返回，但有质量标记
            else:
                self.health.report_failure(platform, "详情返回空")
                return None
        except Exception as e:
            self.health.report_failure(platform, str(e))
            return None

    # ===== 价格 =====

    async def get_price(self, platform: str, product_id: str) -> Optional[float]:
        """获取单个商品价格"""
        detail = await self.get_detail(platform, product_id)
        return detail.get("price") if detail else None

    async def batch_get_prices(
        self, items: list[tuple[str, str]], max_concurrent: int = 10
    ) -> list[dict]:
        """
        批量获取价格

        Args:
            items: [(platform, product_id), ...]
            max_concurrent: 最大并发数

        Returns:
            [{"platform": str, "product_id": str, "price": float|None}, ...]
        """
        await self.initialize()

        semaphore = asyncio.Semaphore(max_concurrent)
        results = []

        async def fetch_one(platform: str, product_id: str) -> dict:
            async with semaphore:
                price = await self.get_price(platform, product_id)
                return {"platform": platform, "product_id": product_id, "price": price}

        tasks = [fetch_one(p, pid) for p, pid in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [
            r if isinstance(r, dict) else {"platform": "", "product_id": "", "price": None, "error": str(r)}
            for r in results
        ]

    # ===== 系统状态 =====

    def get_system_status(self) -> dict:
        """获取系统完整状态"""
        return {
            "initialized": self._initialized,
            "health": self.health.get_status(),
            "quality": self.quality.get_stats(),
            "proxy_pool": _proxy_pool.get_stats(),
            "scrapers": {
                name: scraper.get_stats()
                for name, scraper in self.scrapers.items()
            },
            "alerts": self.health.get_alerts(limit=20),
        }


# 全局单例
scraper_client = ScraperClient()
