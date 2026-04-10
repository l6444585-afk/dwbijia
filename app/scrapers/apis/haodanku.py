"""
好单库 API 客户端

官方文档: https://www.haodanku.com/openapi
提供淘宝/天猫优惠商品的搜索与详情查询，数据更新频率高。
"""

from typing import Optional

import httpx
from loguru import logger

from config.settings import settings

# API 基础地址
_BASE_URL = "https://v2.api.haodanku.com/"

# 请求超时（秒）
_TIMEOUT = 10

# 最大重试次数
_MAX_RETRIES = 3


def _normalize_item(raw: dict) -> dict:
    """将好单库原始数据转换为统一格式"""
    original_price = float(raw.get("itemendprice", 0) or 0)
    coupon_amount = float(raw.get("couponmoney", 0) or 0)
    actual_price = float(raw.get("itemsale", 0) or max(original_price - coupon_amount, 0))

    return {
        "title": raw.get("itemtitle", ""),
        "price": actual_price,
        "image_url": raw.get("itempic", ""),
        "url": raw.get("itemlink", "") or raw.get("couponurl", ""),
        "platform": "taobao",
        "platform_id": str(raw.get("itemid", "")),
        "original_price": original_price,
        "coupon_price": coupon_amount,
        "commission_rate": float(raw.get("tkrate", 0) or 0),
        "shop_name": raw.get("shopname", ""),
        "source": "haodanku",
    }


class HaodankuAPI:
    """
    好单库 API 客户端

    需要配置环境变量:
    - HAODANKU_API_KEY: API Key（好单库后台获取）
    """

    def __init__(self) -> None:
        self._api_key: Optional[str] = settings.HAODANKU_API_KEY

    @property
    def is_configured(self) -> bool:
        """检查 API Key 是否已配置"""
        return bool(self._api_key)

    async def _request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        发送 API 请求，带重试和错误处理

        Returns:
            成功返回完整响应 JSON，失败返回 None
        """
        if not self._api_key:
            raise ValueError("好单库 API 未配置 API_KEY")

        url = f"{_BASE_URL}{endpoint}"
        request_params = {
            "apikey": self._api_key,
            **(params or {}),
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.get(url, params=request_params)

                if resp.status_code == 429:
                    # 触发速率限制，指数退避
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"[好单库] 速率限制，{wait}s 后重试 "
                        f"(第 {attempt}/{_MAX_RETRIES} 次)"
                    )
                    import asyncio
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        f"[好单库] HTTP {resp.status_code} "
                        f"endpoint={endpoint} (第 {attempt}/{_MAX_RETRIES} 次)"
                    )
                    continue

                data = resp.json()

                # 好单库用 code=1 或 code=200 表示成功
                code = data.get("code", -1)
                if code not in (1, 200):
                    logger.warning(
                        f"[好单库] 业务错误: code={code} "
                        f"msg={data.get('msg', '未知')} endpoint={endpoint}"
                    )
                    return None

                return data

            except httpx.TimeoutException:
                logger.warning(
                    f"[好单库] 请求超时 endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
            except httpx.HTTPError as e:
                logger.warning(
                    f"[好单库] 网络错误: {e} endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
            except Exception as e:
                logger.error(
                    f"[好单库] 未知错误: {e} endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
                return None

        logger.error(f"[好单库] 请求失败，已耗尽重试次数 endpoint={endpoint}")
        return None

    async def search(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """
        搜索商品

        Args:
            keyword: 搜索关键词
            page: 页码，从 1 开始
            page_size: 每页数量，最大 100

        Returns:
            统一格式的商品列表
        """
        if not self.is_configured:
            logger.debug("[好单库] 未配置，跳过搜索")
            return []

        data = await self._request(
            "itemlist",
            params={
                "keyword": keyword,
                "back": str(min(page_size, 100)),
                "min_id": str(page),
                "sort": "0",  # 综合排序
            },
        )

        if not data:
            return []

        raw_list = data.get("data", [])
        if not isinstance(raw_list, list):
            return []

        items = [_normalize_item(item) for item in raw_list]
        logger.info(f"[好单库] 搜索 '{keyword}' 返回 {len(items)} 条结果")
        return items

    async def get_detail(self, product_id: str) -> Optional[dict]:
        """
        获取商品详情

        Args:
            product_id: 商品 ID（淘宝商品 ID）

        Returns:
            统一格式的商品信息，未找到返回 None
        """
        if not self.is_configured:
            logger.debug("[好单库] 未配置，跳过详情查询")
            return None

        data = await self._request(
            "item_detail",
            params={
                "itemid": product_id,
            },
        )

        if not data:
            return None

        # 详情接口的数据在 data 字段
        raw = data.get("data")
        if not raw or not isinstance(raw, dict):
            return None

        item = _normalize_item(raw)
        logger.info(f"[好单库] 获取详情成功: {item['title'][:30]}")
        return item
