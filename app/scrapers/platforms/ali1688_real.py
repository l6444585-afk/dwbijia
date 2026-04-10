"""
1688(阿里巴巴批发)真实数据爬虫

数据获取策略（按优先级）:
  1. H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://m.1688.com/offer_search/-{keyword}.html
  - 详情: https://m.1688.com/offer/{product_id}.html

特点: 1688 商品常显示阶梯价/区间价，取最低价存 price，完整区间存 price_range
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
from config.settings import settings


class Ali1688RealScraper(RealBaseScraper):
    platform = "1688"

    def __init__(self) -> None:
        super().__init__()
        self._cookies: dict = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """1688 移动端搜索页"""
        offset = (page - 1) * 20
        return f"https://m.1688.com/offer_search/-{keyword}.html?beginPage={page}&offset={offset}"

    def _get_detail_url(self, product_id: str) -> str:
        """1688 移动端商品详情页"""
        return f"https://m.1688.com/offer/{product_id}.html"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """优先官方 API，否则 H5 移动端 API"""
        if settings.ALI1688_API_KEY and settings.ALI1688_API_URL:
            return await self._call_configured_api(keyword, page)
        return await self._try_h5_api_search(keyword, page)

    async def _call_configured_api(self, keyword: str, page: int) -> Optional[list[dict]]:
        """调用 .env 配置的 1688 开放平台 API"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.ALI1688_API_URL}/search",
                    params={"app_key": settings.ALI1688_API_KEY, "keywords": keyword, "page": page, "page_size": 20},
                    headers={"Authorization": f"Bearer {settings.ALI1688_API_KEY}", "Content-Type": "application/json"},
                )
                data = resp.json()
                items_raw = (
                    data.get("data", {}).get("offerList", [])
                    or data.get("data", {}).get("list", [])
                    or data.get("result", {}).get("offerList", [])
                    or []
                )
                return [self._normalize_api_item(it) for it in items_raw if it.get("subject") or it.get("title")]
        except Exception as e:
            logger.debug(f"[1688] 配置API调用失败: {e}")
            return None

    async def _try_h5_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """尝试 1688 H5 移动端 mtop API（签名流程同淘宝）"""
        try:
            fp = self.fp_gen.generate(mobile=True)
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # 获取 token cookie
                if not self._cookies.get("_m_h5_tk"):
                    init_resp = await client.get("https://m.1688.com", headers=fp.headers)
                    for cookie in init_resp.cookies.jar:
                        self._cookies[cookie.name] = cookie.value

                token = self._cookies.get("_m_h5_tk", "")
                if not token:
                    return None

                token_part = token.split("_")[0] if "_" in token else token
                t = str(int(time.time() * 1000))
                app_key = "12574478"
                data_obj = {"keywords": keyword, "beginPage": page, "pageSize": 20, "sortType": "default"}
                data_str = json.dumps(data_obj, separators=(",", ":"))
                sign = hashlib.md5(f"{token_part}&{t}&{app_key}&{data_str}".encode()).hexdigest()

                resp = await client.get(
                    "https://h5api.m.1688.com/h5/mtop.1688.search/1.0/",
                    params={"appKey": app_key, "t": t, "sign": sign, "api": "mtop.1688.search",
                            "v": "1.0", "type": "jsonp", "dataType": "jsonp", "data": data_str},
                    headers=fp.headers, cookies=self._cookies,
                )
                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value

                # 解析 JSONP 响应
                text = resp.text
                json_match = re.search(r"mtopjsonp\d*\((.*)\)", text)
                result = json.loads(json_match.group(1)) if json_match else json.loads(text)

                offer_list = (
                    result.get("data", {}).get("offerList", [])
                    or result.get("data", {}).get("data", {}).get("offerList", [])
                    or []
                )
                if not offer_list:
                    return None
                return [self._normalize_api_item(it) for it in offer_list if self._has_valid_data(it)]
        except Exception as e:
            logger.debug(f"[1688] H5 API 搜索失败: {e}")
            return None

    # ===== 数据标准化 =====

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化 1688 API 搜索结果"""
        title = (item.get("subject", "") or item.get("title", "") or item.get("offerTitle", "")).strip()
        offer_id = str(item.get("offerId", "") or item.get("id", "") or item.get("productId", ""))
        price, price_range = self._extract_price_range(item)

        # 图片: 优先单张，兜底取列表第一张
        image = item.get("imageUrl", "") or item.get("image", "") or item.get("imgUrl", "") or item.get("pic", "")
        if not image:
            img_list = item.get("imageList", item.get("images", []))
            if img_list and isinstance(img_list, list):
                first = img_list[0]
                image = first if isinstance(first, str) else first.get("url", "")

        # 店铺
        company = item.get("company", {}) if isinstance(item.get("company"), dict) else {}
        shop_name = item.get("shopName", "") or item.get("sellerLoginId", "") or company.get("name", "")

        # 起批量
        moq = self._safe_int(item.get("quantityBegin", "") or item.get("moq", "") or item.get("beginAmount", ""))

        return {
            "platform": "1688",
            "platform_id": offer_id,
            "title": title,
            "price": price,
            "price_range": price_range,
            "original_price": self._safe_float(item.get("originalPrice", item.get("refPrice"))),
            "image_url": self._fix_image_url(image),
            "sales": self._parse_sales(item.get("quantitySumMonth", "") or item.get("monthSold", "") or item.get("sales", "0")),
            "rating": self._safe_float(item.get("repurchaseRate", item.get("rating", 0))),
            "shop_name": shop_name,
            "url": f"https://detail.1688.com/offer/{offer_id}.html",
            "category": item.get("categoryName", ""),
            "brand": item.get("brandName", ""),
            "extra_data": {
                "moq": moq,
                "unit": item.get("unit", "件"),
                "origin": item.get("productFeature", {}).get("origin", "") if isinstance(item.get("productFeature"), dict) else "",
            },
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:  # noqa: ARG002
        """解析 1688 搜索页 HTML（JSON 嵌入数据优先，DOM 兜底）"""
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items
        return self._parse_search_dom(BeautifulSoup(html, "lxml"))

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面 <script> 中提取嵌入的商品 JSON"""
        items: list[dict] = []
        # 1688 页面常见的嵌入数据模式
        patterns = [
            r"window\.__INIT_DATA__\s*=\s*(\{.*?\})\s*;",
            r"window\.__ALIFE_DATA__\s*=\s*(\{.*?\})\s*;",
            r"window\.__DATA__\s*=\s*(\{.*?\})\s*;",
            r"window\.viewData\s*=\s*(\{.*?\})\s*;",
            r"__INITIAL_DATA__\s*=\s*(\{.*?\})\s*</script>",
            r'"offerList"\s*:\s*(\[.*?\])',
            r'"offers"\s*:\s*(\[.*?\])',
            r'"data"\s*:\s*(\{[^<]*?"offerList"[^<]*?\})',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, html, re.DOTALL):
                try:
                    data = json.loads(match)
                    for raw in self._dig_offer_list(data):
                        if isinstance(raw, dict) and self._has_valid_data(raw):
                            try:
                                items.append(self._normalize_api_item(raw))
                            except Exception:
                                continue
                except (json.JSONDecodeError, TypeError):
                    continue
        return items

    def _dig_offer_list(self, data) -> list:
        """递归查找商品列表"""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if any(k in data[0] for k in ("subject", "title", "offerId", "price")):
                return data
        if isinstance(data, dict):
            for key in ("offerList", "offers", "data", "result", "list", "items", "content"):
                if key in data:
                    found = self._dig_offer_list(data[key])
                    if found:
                        return found
        return []

    def _parse_search_dom(self, soup: BeautifulSoup) -> list[dict]:
        """DOM 解析搜索结果（兜底）"""
        items: list[dict] = []
        selectors = ["[class*='offer']", "[class*='product']", "[class*='card']", "[class*='item']", "[class*='goods']"]
        cards: list = []
        for sel in selectors:
            cards = soup.select(sel)
            if len(cards) >= 3:
                break
        for card in cards:
            try:
                item = self._parse_offer_card(card)
                if item and item.get("price", 0) > 0:
                    items.append(item)
            except Exception:
                continue
        return items

    def _parse_offer_card(self, card) -> Optional[dict]:
        """解析单个商品卡片 DOM"""
        title_el = card.select_one("[class*='title'], [class*='name'], [class*='subject'], h3")
        title = title_el.get_text(strip=True) if title_el else ""

        price, price_range = 0.0, ""
        price_el = card.select_one("[class*='price']")
        if price_el:
            price, price_range = self._parse_price_text(price_el.get_text(strip=True))

        img_el = card.select_one("img")
        image_url = (img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy") or "") if img_el else ""

        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            id_match = re.search(r"offer/(\d+)", link_el.get("href", "")) or re.search(r"offerId=(\d+)", link_el.get("href", ""))
            if id_match:
                product_id = id_match.group(1)
        if not product_id:
            product_id = card.get("data-offer-id", card.get("data-id", ""))

        sales_el = card.select_one("[class*='sale'], [class*='sold'], [class*='deal']")
        sales = self._parse_sales(sales_el.get_text(strip=True)) if sales_el else 0
        shop_el = card.select_one("[class*='shop'], [class*='company'], [class*='seller']")
        shop_name = shop_el.get_text(strip=True) if shop_el else ""

        if not title or not price:
            return None
        return {
            "platform": "1688", "platform_id": str(product_id), "title": title,
            "price": price, "price_range": price_range, "original_price": None,
            "image_url": self._fix_image_url(image_url), "sales": sales, "rating": 0,
            "shop_name": shop_name,
            "url": f"https://detail.1688.com/offer/{product_id}.html" if product_id else "",
        }

    # ===== 详情页解析 =====

    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """解析 1688 商品详情页 HTML"""
        price = 0.0
        for pat in (r'"price"\s*:\s*"?([\d.]+)"?', r'"salePrice"\s*:\s*"?([\d.]+)"?',
                    r'"promotionPrice"\s*:\s*"?([\d.]+)"?', r'"tradePrice"\s*:\s*"?([\d.]+)"?'):
            m = re.search(pat, html)
            if m:
                price = self._safe_float(m.group(1))
                if price > 0:
                    break

        # 提取价格区间
        price_range = ""
        range_match = re.search(r'"priceRange"\s*:\s*"([^"]+)"', html)
        if range_match:
            price_range = range_match.group(1)
        else:
            all_prices = [self._safe_float(p) for p in re.findall(r'"price"\s*:\s*"?([\d.]+)"?', html)]
            valid = [p for p in all_prices if p > 0]
            if len(valid) >= 2:
                min_p, max_p = min(valid), max(valid)
                if min_p != max_p:
                    price_range = f"{min_p:.2f}-{max_p:.2f}"
                if price <= 0:
                    price = min_p

        # 标题
        title_match = (re.search(r'"subject"\s*:\s*"([^"]+)"', html)
                       or re.search(r'"title"\s*:\s*"([^"]+)"', html)
                       or re.search(r'"offerTitle"\s*:\s*"([^"]+)"', html))
        title = title_match.group(1) if title_match else ""
        if not title:
            soup = BeautifulSoup(html, "lxml")
            el = soup.select_one("title, h1, [class*='title'], [class*='subject']")
            title = el.get_text(strip=True) if el else f"1688商品 {product_id}"

        img_match = re.search(r'"imageUrl"\s*:\s*"([^"]+)"', html) or re.search(r'"images"\s*:\s*\["([^"]+)"', html)
        image_url = img_match.group(1) if img_match else ""

        if price <= 0:
            return None
        return {
            "platform": "1688", "platform_id": product_id, "title": title,
            "price": price, "price_range": price_range,
            "image_url": self._fix_image_url(image_url),
            "url": f"https://detail.1688.com/offer/{product_id}.html",
        }

    async def _wait_for_content(self, page) -> None:
        """等待 1688 页面关键内容加载"""
        try:
            await page.wait_for_selector(
                "[class*='offer'], [class*='product'], [class*='card'], [class*='item']", timeout=10000)
        except Exception:
            await asyncio.sleep(3)

    # ===== 价格处理（1688 特有：阶梯价/区间价） =====

    def _extract_price_range(self, item: dict) -> tuple[float, str]:
        """提取价格和区间。返回 (最低价, 区间字符串)"""
        # 方式1: priceRange 字符串
        range_str = item.get("priceRange", "") or item.get("price_range", "")
        if range_str and "-" in str(range_str):
            min_price, pr = self._parse_price_text(str(range_str))
            if min_price > 0:
                return min_price, pr

        # 方式2: priceInfo 阶梯价列表
        price_info = item.get("priceInfo", item.get("skuInfos", []))
        if isinstance(price_info, list) and price_info:
            prices = [self._safe_float(t.get("price", 0)) for t in price_info if isinstance(t, dict)]
            prices = [p for p in prices if p > 0]
            if prices:
                mn, mx = min(prices), max(prices)
                return mn, f"{mn:.2f}-{mx:.2f}" if mn != mx else ""

        # 方式3: 单价字段
        for key in ("price", "salePrice", "tradePrice", "promotionPrice", "currentPrice"):
            val = item.get(key)
            if val is not None:
                p = self._safe_float(val)
                if p > 0:
                    return p, ""
        return 0.0, ""

    @staticmethod
    def _parse_price_text(text: str) -> tuple[float, str]:
        """解析价格文本。"¥3.50 - ¥8.00" → (3.5, "3.50-8.00")"""
        cleaned = re.sub(r"[¥￥$\s]", "", text)
        range_match = re.match(r"([\d.]+)\s*[-~]\s*([\d.]+)", cleaned)
        if range_match:
            low, high = float(range_match.group(1)), float(range_match.group(2))
            return min(low, high), f"{low:.2f}-{high:.2f}"
        single = re.search(r"([\d.]+)", cleaned)
        return (float(single.group(1)), "") if single else (0.0, "")

    # ===== 工具方法 =====

    @staticmethod
    def _has_valid_data(item: dict) -> bool:
        """检查商品数据有效性（至少有标题和 ID）"""
        return bool(item.get("subject") or item.get("title") or item.get("offerTitle")) and \
               bool(item.get("offerId") or item.get("id") or item.get("productId"))

    @staticmethod
    def _safe_float(val) -> float:
        if val is None:
            return 0.0
        try:
            return float(re.sub(r"[^\d.]", "", str(val)))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_int(val) -> int:
        if not val:
            return 0
        try:
            return int(float(re.sub(r"[^\d.]", "", str(val))))
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
