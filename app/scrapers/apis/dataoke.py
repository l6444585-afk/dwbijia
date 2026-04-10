"""
大淘客 API 客户端

官方文档: https://www.dataoke.com/openapi
提供淘宝/天猫优惠商品的搜索与详情查询，包含优惠券、佣金等信息。
"""

import hashlib
import time
from typing import Optional

import httpx
from loguru import logger

from config.settings import settings

# API 基础地址
_BASE_URL = "https://openapi.dataoke.com/api/goods/"

# 请求超时（秒）
_TIMEOUT = 10

# 最大重试次数
_MAX_RETRIES = 3


def _sign_params(params: dict, app_secret: str) -> str:
    """
    生成大淘客 API 签名

    规则: 将参数按 key 排序拼接后加上 app_secret，取 MD5 大写
    """
    sorted_keys = sorted(params.keys())
    sign_str = "&".join(f"{k}={params[k]}" for k in sorted_keys)
    sign_str += f"&key={app_secret}"
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


def _normalize_item(raw: dict) -> dict:
    """将大淘客原始数据转换为统一格式"""
    # 优惠券后价格：原价 - 优惠券面额
    original_price = float(raw.get("originalPrice", 0) or 0)
    coupon_amount = float(raw.get("couponPrice", 0) or 0)
    actual_price = float(raw.get("actualPrice", 0) or original_price - coupon_amount)

    return {
        "title": raw.get("dtitle") or raw.get("title", ""),
        "price": actual_price,
        "image_url": raw.get("mainPic", ""),
        "url": raw.get("itemLink", ""),
        "platform": "taobao",
        "platform_id": str(raw.get("goodsId", "")),
        "original_price": original_price,
        "coupon_price": coupon_amount,
        "commission_rate": float(raw.get("commissionRate", 0) or 0),
        "shop_name": raw.get("shopName", ""),
        "source": "dataoke",
    }


class DataokeAPI:
    """
    大淘客 API 客户端

    需要配置环境变量:
    - DATAOKE_APP_KEY: 应用 Key
    - DATAOKE_APP_SECRET: 应用 Secret
    """

    def __init__(self) -> None:
        self._app_key: Optional[str] = settings.DATAOKE_APP_KEY
        self._app_secret: Optional[str] = settings.DATAOKE_APP_SECRET

    @property
    def is_configured(self) -> bool:
        """检查 API 密钥是否已配置"""
        return bool(self._app_key and self._app_secret)

    def _build_params(self, **kwargs: object) -> dict:
        """构建带签名的请求参数"""
        if not self._app_key or not self._app_secret:
            raise ValueError("大淘客 API 未配置 APP_KEY 或 APP_SECRET")

        params: dict = {
            "appKey": self._app_key,
            "version": "v1.3.0",
            "nonce": str(int(time.time() * 1000)),
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        params["sign"] = _sign_params(params, self._app_secret)
        return params

    async def _request(self, endpoint: str, **kwargs: object) -> Optional[dict]:
        """
        发送 API 请求，带重试和错误处理

        Returns:
            成功返回响应 data 字段，失败返回 None
        """
        url = f"{_BASE_URL}{endpoint}"
        params = self._build_params(**kwargs)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.get(url, params=params)

                if resp.status_code == 429:
                    # 触发速率限制，等待后重试
                    wait = min(2 ** attempt, 10)
                    logger.warning(
                        f"[大淘客] 速率限制，{wait}s 后重试 "
                        f"(第 {attempt}/{_MAX_RETRIES} 次)"
                    )
                    import asyncio
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        f"[大淘客] HTTP {resp.status_code} "
                        f"endpoint={endpoint} (第 {attempt}/{_MAX_RETRIES} 次)"
                    )
                    continue

                data = resp.json()
                if data.get("code") != 1:
                    logger.warning(
                        f"[大淘客] 业务错误: code={data.get('code')} "
                        f"msg={data.get('msg', '未知')} endpoint={endpoint}"
                    )
                    return None

                return data.get("data")

            except httpx.TimeoutException:
                logger.warning(
                    f"[大淘客] 请求超时 endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
            except httpx.HTTPError as e:
                logger.warning(
                    f"[大淘客] 网络错误: {e} endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
            except Exception as e:
                logger.error(
                    f"[大淘客] 未知错误: {e} endpoint={endpoint} "
                    f"(第 {attempt}/{_MAX_RETRIES} 次)"
                )
                return None

        logger.error(f"[大淘客] 请求失败，已耗尽重试次数 endpoint={endpoint}")
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
            page_size: 每页数量，最大 200

        Returns:
            统一格式的商品列表
        """
        if not self.is_configured:
            logger.debug("[大淘客] 未配置，跳过搜索")
            return []

        data = await self._request(
            "get-goods-list",
            pageId=str(page),
            pageSize=str(min(page_size, 200)),
            keyWords=keyword,
            sort="0",  # 综合排序
        )

        if not data or not isinstance(data, dict):
            return []

        raw_list = data.get("list", [])
        if not isinstance(raw_list, list):
            return []

        items = [_normalize_item(item) for item in raw_list]
        logger.info(f"[大淘客] 搜索 '{keyword}' 返回 {len(items)} 条结果")
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
            logger.debug("[大淘客] 未配置，跳过详情查询")
            return None

        data = await self._request(
            "get-goods-details",
            id=product_id,
        )

        if not data:
            return None

        # 详情接口直接返回商品对象（非列表）
        if isinstance(data, dict):
            item = _normalize_item(data)
            logger.info(f"[大淘客] 获取详情成功: {item['title'][:30]}")
            return item

        return None
