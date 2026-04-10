"""
得物(Dewu/Poizon)真实数据爬虫

数据获取策略（按优先级）:
  1. 得物 H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://m.dewu.com/search/result?keyword={keyword}
  - 详情: https://m.dewu.com/router/product/detail?spuId={id}
"""
import asyncio
import re
import json
import time
import hashlib
from typing import Optional
from loguru import logger

import httpx
from bs4 import BeautifulSoup

from app.scrapers.platforms.base import RealBaseScraper
from app.scrapers.engine.fingerprint import FingerprintGenerator
from config.settings import settings


class DewuRealScraper(RealBaseScraper):
    platform = "dewu"

    def __init__(self):
        super().__init__()
        self._cookies: dict = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """得物移动端搜索页"""
        return f"https://m.dewu.com/search/result?keyword={keyword}&page={page}"

    def _get_detail_url(self, product_id: str) -> str:
        """得物商品详情页"""
        return f"https://m.dewu.com/router/product/detail?spuId={product_id}"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        尝试调用得物 H5 API 搜索
        """
        # 优先使用配置的 API
        if settings.DEWU_API_KEY and settings.DEWU_API_URL:
            return await self._call_configured_api(keyword, page)

        # 尝试得物 H5 API
        return await self._try_h5_api_search(keyword, page)

    async def _call_configured_api(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        调用配置的得物 API（官方合作/第三方）

        ================================================
        在 .env 配置:
          DEWU_API_KEY=你的API密钥
          DEWU_API_SECRET=你的Secret
          DEWU_API_URL=API基础地址
        ================================================
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {
                    "Authorization": f"Bearer {settings.DEWU_API_KEY}",
                    "Content-Type": "application/json",
                }
                resp = await client.get(
                    f"{settings.DEWU_API_URL}/search",
                    params={"keyword": keyword, "page": page, "limit": 20},
                    headers=headers,
                )
                data = resp.json()
                items_raw = data.get("data", {}).get("list", data.get("list", []))
                return [self._normalize_api_item(item) for item in items_raw if item.get("title")]
        except Exception as e:
            logger.debug(f"[得物] 配置API调用失败: {e}")
            return None

    async def _try_h5_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        尝试调用得物 H5 API

        得物 H5 API 端点:
        - 搜索: POST https://app.dewu.com/api/v1/h5/search/fire/search/list
        - 详情: GET https://app.dewu.com/api/v1/h5/index/fire/flow/detail
        """
        try:
            fp = self.fp_gen.generate(mobile=True)
            headers = {
                **fp.headers,
                "Referer": "https://m.dewu.com/",
                "Origin": "https://m.dewu.com",
                "Content-Type": "application/json",
            }

            payload = {
                "title": keyword,
                "page": str(page - 1),  # 得物从0开始
                "limit": "20",
                "showHot": "-1",
                "sortType": "0",
                "sortMode": "1",
                "unionId": "",
            }

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://app.dewu.com/api/v1/h5/search/fire/search/list",
                    json=payload,
                    headers=headers,
                    cookies=self._cookies,
                )

                # 更新cookies
                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value

                if resp.status_code != 200:
                    return None

                data = resp.json()

                if data.get("code") != 200 and data.get("status") != 200:
                    return None

                product_list = (
                    data.get("data", {}).get("productList", [])
                    or data.get("data", {}).get("list", [])
                    or []
                )

                if not product_list:
                    return None

                return [self._normalize_api_item(item) for item in product_list if self._has_valid_data(item)]

        except Exception as e:
            logger.debug(f"[得物] H5 API 搜索失败: {e}")
            return None

    async def _try_api_detail(self, product_id: str) -> Optional[dict]:
        """尝试通过 API 获取商品详情"""
        try:
            fp = self.fp_gen.generate(mobile=True)
            headers = {
                **fp.headers,
                "Referer": f"https://m.dewu.com/router/product/detail?spuId={product_id}",
                "Origin": "https://m.dewu.com",
            }

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://app.dewu.com/api/v1/h5/index/fire/flow/detail",
                    params={"spuId": product_id, "productSourceName": ""},
                    headers=headers,
                    cookies=self._cookies,
                )

                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value

                if resp.status_code != 200:
                    return None

                data = resp.json()
                detail = data.get("data", {})

                if not detail:
                    return None

                return self._normalize_detail(detail, product_id)

        except Exception as e:
            logger.debug(f"[得物] API 详情获取失败: {e}")
            return None

    # ===== 数据标准化 =====

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化得物API搜索结果"""
        # 价格处理 - 得物价格可能以分为单位
        price = self._extract_price(item)

        # 商品ID
        spu_id = str(
            item.get("spuId", "")
            or item.get("productId", "")
            or item.get("id", "")
        )

        # 图片
        image = (
            item.get("logoUrl", "")
            or item.get("imgUrl", "")
            or item.get("image", "")
            or item.get("pic", "")
        )

        # 销量
        sales = self._parse_sales(
            item.get("soldNum", "")
            or item.get("salesVolume", "")
            or item.get("sales", "0")
        )

        return {
            "platform": "dewu",
            "platform_id": spu_id,
            "title": (item.get("title", "") or item.get("spuName", "")).strip(),
            "price": price,
            "original_price": self._safe_float(item.get("originalPrice", item.get("tagPrice"))),
            "image_url": self._fix_image_url(image),
            "sales": sales,
            "rating": self._safe_float(item.get("score", item.get("rating", 0))),
            "shop_name": "得物",
            "url": f"https://m.dewu.com/router/product/detail?spuId={spu_id}",
            "brand": item.get("brandName", item.get("brand", "")),
            "category": item.get("categoryName", ""),
            "extra_data": {
                "authentication": "得物鉴别",
                "article_number": item.get("articleNumber", ""),
            },
        }

    def _normalize_detail(self, detail: dict, product_id: str) -> dict:
        """标准化得物商品详情"""
        # 基本信息
        info = detail.get("detail", detail)

        # 最低价格（各尺码中最低的）
        price = self._extract_price(info)
        sku_list = info.get("skus", info.get("sizeList", []))
        if sku_list:
            prices = []
            for sku in sku_list:
                p = self._extract_price(sku)
                if p > 0:
                    prices.append(p)
            if prices:
                price = min(prices)

        return {
            "platform": "dewu",
            "platform_id": product_id,
            "title": info.get("title", info.get("spuName", f"得物商品 {product_id}")),
            "price": price,
            "original_price": self._safe_float(info.get("originalPrice", info.get("tagPrice"))),
            "image_url": self._fix_image_url(info.get("logoUrl", info.get("imgUrl", ""))),
            "sales": self._parse_sales(info.get("soldNum", "0")),
            "rating": self._safe_float(info.get("score", 0)),
            "shop_name": "得物",
            "url": f"https://m.dewu.com/router/product/detail?spuId={product_id}",
            "brand": info.get("brandName", ""),
            "extra_data": {
                "authentication": "得物鉴别",
                "article_number": info.get("articleNumber", ""),
                "sku_count": len(sku_list) if sku_list else 0,
            },
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:
        """解析得物搜索页HTML"""
        items = []

        # 策略1: 从嵌入JSON提取（得物H5是SPA，数据嵌在__NEXT_DATA__或类似结构中）
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items

        # 策略2: DOM解析
        soup = BeautifulSoup(html, "lxml")
        return self._parse_search_dom(soup)

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面嵌入JavaScript中提取商品数据"""
        items = []

        patterns = [
            r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>",
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.__DATA__\s*=\s*(\{.*?\})\s*;",
            r'"productList"\s*:\s*(\[.*?\])',
            r'"list"\s*:\s*(\[.*?\])\s*,\s*"(?:total|page)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)

                    # 提取商品列表
                    item_list = self._dig_product_list(data)

                    for raw in item_list:
                        if not isinstance(raw, dict):
                            continue
                        if self._has_valid_data(raw):
                            try:
                                items.append(self._normalize_api_item(raw))
                            except Exception:
                                continue

                except (json.JSONDecodeError, TypeError):
                    continue

        return items

    def _dig_product_list(self, data) -> list:
        """递归查找商品列表"""
        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict) and any(
                k in data[0] for k in ("title", "spuName", "spuId", "price")
            ):
                return data

        if isinstance(data, dict):
            for key in ("productList", "list", "items", "data", "result", "props", "pageProps"):
                if key in data:
                    result = self._dig_product_list(data[key])
                    if result:
                        return result
        return []

    def _parse_search_dom(self, soup: BeautifulSoup) -> list[dict]:
        """DOM解析得物搜索结果"""
        items = []

        selectors = [
            "[class*='product']",
            "[class*='card']",
            "[class*='item']",
            "[class*='goods']",
        ]

        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if len(cards) >= 3:
                break

        for card in cards:
            try:
                item = self._parse_product_card(card)
                if item and item.get("price", 0) > 0:
                    items.append(item)
            except Exception:
                continue

        return items

    def _parse_product_card(self, card) -> Optional[dict]:
        """解析单个得物商品卡片"""
        title_el = card.select_one("[class*='title'], [class*='name'], h3")
        title = title_el.get_text(strip=True) if title_el else ""

        price = 0
        price_el = card.select_one("[class*='price']")
        if price_el:
            price_text = price_el.get_text(strip=True)
            price = self._safe_float(re.sub(r"[^\d.]", "", price_text))

        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            id_match = re.search(r"spuId=(\d+)", href) or re.search(r"detail/(\d+)", href)
            if id_match:
                product_id = id_match.group(1)

        if not title or not price:
            return None

        return {
            "platform": "dewu",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "original_price": None,
            "image_url": self._fix_image_url(image_url),
            "sales": 0,
            "rating": 0,
            "shop_name": "得物",
            "url": f"https://m.dewu.com/router/product/detail?spuId={product_id}" if product_id else "",
            "brand": "",
            "extra_data": {"authentication": "得物鉴别"},
        }

    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """解析得物商品详情页"""
        # JSON提取
        patterns = [
            r'"price"\s*:\s*"?([\d.]+)"?',
            r'"minPrice"\s*:\s*"?([\d.]+)"?',
            r'"lowestPrice"\s*:\s*"?([\d.]+)"?',
        ]

        price = 0
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                price = self._safe_float(m.group(1))
                if price > 0:
                    # 得物价格如果大于10000可能是分为单位
                    if price > 100000:
                        price /= 100
                    break

        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', html) or re.search(r'"spuName"\s*:\s*"([^"]+)"', html)
        title = title_match.group(1) if title_match else ""

        if not title:
            soup = BeautifulSoup(html, "lxml")
            title_el = soup.select_one("title, h1, [class*='title'], [class*='name']")
            title = title_el.get_text(strip=True) if title_el else f"得物商品 {product_id}"

        if price <= 0:
            return None

        return {
            "platform": "dewu",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "url": f"https://m.dewu.com/router/product/detail?spuId={product_id}",
            "shop_name": "得物",
            "extra_data": {"authentication": "得物鉴别"},
        }

    async def _wait_for_content(self, page):
        """等待得物页面加载"""
        try:
            await page.wait_for_selector(
                "[class*='product'], [class*='card'], [class*='item'], [class*='goods']",
                timeout=10000,
            )
        except Exception:
            await asyncio.sleep(3)

    # ===== 工具方法 =====

    def _extract_price(self, item: dict) -> float:
        """提取价格 - 处理得物特殊的价格格式"""
        for key in ("price", "minPrice", "lowestPrice", "sellPrice", "currentPrice"):
            val = item.get(key)
            if val is not None:
                p = self._safe_float(val)
                if p > 0:
                    # 大于10万可能是分为单位
                    if p > 100000:
                        p /= 100
                    return p
        return 0

    @staticmethod
    def _has_valid_data(item: dict) -> bool:
        return bool(
            item.get("title") or item.get("spuName")
        ) and bool(
            item.get("spuId") or item.get("productId") or item.get("id")
        )

    @staticmethod
    def _safe_float(val) -> float:
        if val is None:
            return 0
        try:
            return float(re.sub(r"[^\d.]", "", str(val)))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_sales(val) -> int:
        if not val:
            return 0
        s = str(val).replace(",", "").replace("+", "")
        m = re.search(r"([\d.]+)", s)
        if not m:
            return 0
        num = float(m.group(1))
        if "万" in str(val):
            num *= 10000
        return int(num)

    @staticmethod
    def _fix_image_url(url: str) -> str:
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url
