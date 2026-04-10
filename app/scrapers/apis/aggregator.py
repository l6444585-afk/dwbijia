"""
第三方 API 聚合器

统一调用所有已配置的第三方API，合并去重后返回结果。
用于补充爬虫数据源，尤其是优惠券和佣金信息。
"""

import asyncio
from typing import Optional

from loguru import logger

from app.scrapers.apis.dataoke import DataokeAPI
from app.scrapers.apis.haodanku import HaodankuAPI


class PriceAggregator:
    """
    价格聚合器

    自动检测哪些第三方 API 已配置，并发调用后合并去重。
    未配置的 API 会被跳过，不会报错。
    """

    def __init__(self) -> None:
        self._apis: dict[str, DataokeAPI | HaodankuAPI] = {
            "dataoke": DataokeAPI(),
            "haodanku": HaodankuAPI(),
        }

    def get_available_apis(self) -> list[str]:
        """返回已配置可用的 API 名称列表"""
        return [
            name
            for name, api in self._apis.items()
            if api.is_configured
        ]

    async def search(self, keyword: str, page: int = 1) -> dict:
        """
        聚合搜索所有已配置的第三方 API

        Args:
            keyword: 搜索关键词
            page: 页码

        Returns:
            {
                "keyword": str,
                "items": list[dict],       # 去重后的商品列表
                "total": int,              # 去重后总数
                "sources": dict[str, int], # 各来源贡献数量
                "errors": list[str],       # 出错的 API 名称
            }
        """
        available = self.get_available_apis()
        if not available:
            logger.info("[聚合器] 无可用第三方 API，返回空结果")
            return {
                "keyword": keyword,
                "items": [],
                "total": 0,
                "sources": {},
                "errors": [],
            }

        logger.info(f"[聚合器] 搜索 '{keyword}'，可用API: {available}")

        # 并发调用所有可用 API
        tasks: dict[str, asyncio.Task[list[dict]]] = {}
        async with asyncio.TaskGroup() as tg:
            for name in available:
                api = self._apis[name]
                tasks[name] = tg.create_task(
                    self._safe_search(name, api, keyword, page)
                )

        # 收集结果
        all_items: list[dict] = []
        sources: dict[str, int] = {}
        errors: list[str] = []

        for name, task in tasks.items():
            items = task.result()
            if items is None:
                errors.append(name)
                sources[name] = 0
            else:
                sources[name] = len(items)
                all_items.extend(items)

        # 按 platform_id 去重（保留第一个出现的）
        deduplicated = _deduplicate_items(all_items)

        logger.info(
            f"[聚合器] 搜索完成: 原始 {len(all_items)} 条, "
            f"去重后 {len(deduplicated)} 条, "
            f"来源分布 {sources}"
        )

        return {
            "keyword": keyword,
            "items": deduplicated,
            "total": len(deduplicated),
            "sources": sources,
            "errors": errors,
        }

    async def get_detail(
        self,
        product_id: str,
    ) -> Optional[dict]:
        """
        从所有已配置 API 获取商品详情，返回第一个成功的结果

        Args:
            product_id: 商品 ID

        Returns:
            统一格式的商品信息，全部失败返回 None
        """
        for name in self.get_available_apis():
            api = self._apis[name]
            try:
                result = await api.get_detail(product_id)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"[聚合器] {name} 详情查询异常: {e}")
                continue

        return None

    @staticmethod
    async def _safe_search(
        name: str,
        api: DataokeAPI | HaodankuAPI,
        keyword: str,
        page: int,
    ) -> Optional[list[dict]]:
        """安全调用单个 API 的搜索，异常时返回 None 而非抛出"""
        try:
            return await api.search(keyword, page=page)
        except Exception as e:
            logger.error(f"[聚合器] {name} 搜索异常: {e}")
            return None


def _deduplicate_items(items: list[dict]) -> list[dict]:
    """
    按 platform_id 去重，保留第一个出现的记录

    没有 platform_id 的条目直接保留（不参与去重）。
    """
    seen: set[str] = set()
    result: list[dict] = []

    for item in items:
        pid = item.get("platform_id", "")
        if not pid:
            result.append(item)
            continue
        if pid not in seen:
            seen.add(pid)
            result.append(item)

    return result
