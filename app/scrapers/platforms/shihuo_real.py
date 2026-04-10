"""
识货(Shihuo)真实数据爬虫

数据获取策略（按优先级）:
  1. 识货 H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://m.shihuo.cn/search?keyword={keyword}
  - 详情: https://m.shihuo.cn/product/{id}
"""
import asyncio
import re
import json
from typing import Optional
from urllib.parse import quote

from loguru import logger
import httpx
from bs4 import BeautifulSoup

from app.scrapers.platforms.base import RealBaseScraper
from config.settings import settings


class ShihuoRealScraper(RealBaseScraper):
    platform = "shihuo"

    # H5 API 搜索端点（按可靠性排序）
    _SEARCH_ENDPOINTS = [
        ("POST", "https://m.shihuo.cn/gateway/search"),
        ("POST", "https://m.shihuo.cn/api/search"),
        ("GET", "https://api.shihuo.cn/mc/search/list"),
    ]
    # H5 API 详情端点
    _DETAIL_ENDPOINTS = [
        "https://m.shihuo.cn/gateway/product/detail",
        "https://m.shihuo.cn/api/product/detail",
        "https://api.shihuo.cn/mc/product/detail",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._cookies: dict[str, str] = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """识货移动端搜索页"""
        return f"https://m.shihuo.cn/search?keyword={quote(keyword)}&page={page}"

    def _get_detail_url(self, product_id: str) -> str:
        """识货商品详情页"""
        return f"https://m.shihuo.cn/product/{product_id}"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """尝试调用识货 H5 API 搜索"""
        if settings.SHIHUO_API_KEY and settings.SHIHUO_API_URL:
            return await self._call_configured_api(keyword, page)
        return await self._try_h5_api_search(keyword, page)

    async def _call_configured_api(self, keyword: str, page: int) -> Optional[list[dict]]:
        """调用 .env 中配置的识货 API"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.SHIHUO_API_URL}/search",
                    params={"keyword": keyword, "page": page, "limit": 20},
                    headers={
                        "Authorization": f"Bearer {settings.SHIHUO_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                data = resp.json()
                items_raw = data.get("data", {}).get("list", data.get("list", []))
                return [self._normalize_api_item(it) for it in items_raw if it.get("title")]
        except Exception as e:
            logger.debug(f"[识货] 配置API调用失败: {e}")
            return None

    async def _try_h5_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """依次尝试多个识货 H5 API 端点"""
        for method, url in self._SEARCH_ENDPOINTS:
            result = await self._try_single_api_endpoint(method, url, keyword, page)
            if result:
                return result
        return None

    async def _try_single_api_endpoint(
        self, method: str, url: str, keyword: str, page: int
    ) -> Optional[list[dict]]:
        """尝试单个API端点"""
        try:
            fp = self.fp_gen.generate(mobile=True)
            headers = {
                **fp.headers,
                "Referer": "https://m.shihuo.cn/",
                "Origin": "https://m.shihuo.cn",
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
            }
            params = {"keyword": keyword, "page": str(page), "pageSize": "20", "sortType": "0"}

            async with httpx.AsyncClient(timeout=10) as client:
                if method == "POST":
                    resp = await client.post(url, json=params, headers=headers, cookies=self._cookies)
                else:
                    resp = await client.get(url, params=params, headers=headers, cookies=self._cookies)

                self._update_cookies(resp)
                if resp.status_code != 200:
                    return None

                data = resp.json()
                status = data.get("code", data.get("status", data.get("errno", -1)))
                if status not in (0, 200, "0", "200"):
                    return None

                product_list = (
                    data.get("data", {}).get("list", [])
                    or data.get("data", {}).get("productList", [])
                    or data.get("data", {}).get("items", [])
                    or data.get("list", [])
                )
                if not product_list:
                    return None

                return [self._normalize_api_item(it) for it in product_list if self._has_valid_data(it)]
        except Exception as e:
            logger.debug(f"[识货] H5 API ({url}) 搜索失败: {e}")
            return None

    async def _try_api_detail(self, product_id: str) -> Optional[dict]:
        """尝试通过 API 获取商品详情"""
        for url in self._DETAIL_ENDPOINTS:
            try:
                fp = self.fp_gen.generate(mobile=True)
                headers = {
                    **fp.headers,
                    "Referer": f"https://m.shihuo.cn/product/{product_id}",
                    "Origin": "https://m.shihuo.cn",
                }
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        url, params={"id": product_id, "productId": product_id},
                        headers=headers, cookies=self._cookies,
                    )
                    self._update_cookies(resp)
                    if resp.status_code != 200:
                        continue
                    detail = resp.json().get("data", {})
                    if detail:
                        return self._normalize_detail(detail, product_id)
            except Exception as e:
                logger.debug(f"[识货] API ({url}) 详情获取失败: {e}")
        return None

    # ===== 数据标准化 =====

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化识货API搜索结果"""
        product_id = str(
            item.get("productId", "") or item.get("id", "")
            or item.get("goodsId", "") or item.get("spuId", "")
        )
        image = (
            item.get("imgUrl", "") or item.get("image", "") or item.get("pic", "")
            or item.get("logoUrl", "") or item.get("coverUrl", "")
        )
        title = (item.get("title", "") or item.get("productName", "") or item.get("name", "")).strip()

        return {
            "platform": "shihuo",
            "platform_id": product_id,
            "title": title,
            "price": self._extract_price(item),
            "original_price": self._safe_float(
                item.get("originalPrice", item.get("tagPrice", item.get("marketPrice")))
            ),
            "image_url": self._fix_image_url(image),
            "sales": self._parse_sales(
                item.get("salesVolume", "") or item.get("soldNum", "")
                or item.get("sales", "") or item.get("saleCount", "0")
            ),
            "rating": self._safe_float(item.get("score", item.get("rating", 0))),
            "shop_name": item.get("shopName", item.get("sellerName", "识货")),
            "url": f"https://m.shihuo.cn/product/{product_id}",
            "brand": item.get("brandName", item.get("brand", "")),
            "category": item.get("categoryName", item.get("category", "")),
            "extra_data": {
                "source_platform": item.get("sourcePlatform", ""),
                "channel": item.get("channel", ""),
            },
        }

    def _normalize_detail(self, detail: dict, product_id: str) -> dict:
        """标准化识货商品详情"""
        info = detail.get("detail", detail)
        price = self._extract_price(info)

        # 多渠道/多尺码取最低价
        sku_list = info.get("skus", []) or info.get("sizeList", []) or info.get("priceList", [])
        if sku_list:
            valid_prices = [p for sku in sku_list if (p := self._extract_price(sku)) > 0]
            if valid_prices:
                price = min(valid_prices)

        title = (
            info.get("title", "") or info.get("productName", "")
            or info.get("name", "") or f"识货商品 {product_id}"
        )
        image = (
            info.get("imgUrl", "") or info.get("image", "")
            or info.get("logoUrl", "") or info.get("coverUrl", "")
        )

        return {
            "platform": "shihuo",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "original_price": self._safe_float(
                info.get("originalPrice", info.get("tagPrice", info.get("marketPrice")))
            ),
            "image_url": self._fix_image_url(image),
            "sales": self._parse_sales(info.get("salesVolume", info.get("soldNum", "0"))),
            "rating": self._safe_float(info.get("score", 0)),
            "shop_name": info.get("shopName", "识货"),
            "url": f"https://m.shihuo.cn/product/{product_id}",
            "brand": info.get("brandName", ""),
            "extra_data": {
                "source_platform": info.get("sourcePlatform", ""),
                "channel": info.get("channel", ""),
                "sku_count": len(sku_list) if sku_list else 0,
            },
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:
        """解析识货搜索页HTML"""
        # 策略1: 从嵌入JSON提取（识货H5是SPA，数据嵌在script标签中）
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items
        # 策略2: DOM解析兜底
        return self._parse_search_dom(BeautifulSoup(html, "lxml"))

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面嵌入JavaScript中提取商品数据"""
        items: list[dict] = []
        # 识货常见的前端数据注入模式
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>",
            r"window\.__DATA__\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r'"productList"\s*:\s*(\[.*?\])',
            r'"list"\s*:\s*(\[.*?\])\s*,\s*"(?:total|page|count)',
            r'"items"\s*:\s*(\[.*?\])\s*,\s*"(?:total|page|count)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, html, re.DOTALL):
                try:
                    data = json.loads(match)
                    for raw in self._dig_product_list(data):
                        if isinstance(raw, dict) and self._has_valid_data(raw):
                            try:
                                items.append(self._normalize_api_item(raw))
                            except Exception:
                                continue
                except (json.JSONDecodeError, TypeError):
                    continue
        return items

    def _dig_product_list(self, data: object) -> list:
        """递归查找商品列表"""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if any(k in data[0] for k in ("title", "productName", "name", "productId", "price")):
                return data
        if isinstance(data, dict):
            for key in ("productList", "list", "items", "data", "result", "props", "pageProps", "goods", "products"):
                if key in data:
                    result = self._dig_product_list(data[key])
                    if result:
                        return result
        return []

    def _parse_search_dom(self, soup: BeautifulSoup) -> list[dict]:
        """DOM解析识货搜索结果"""
        items: list[dict] = []
        cards: list = []
        for sel in ("[class*='product']", "[class*='goods']", "[class*='card']", "[class*='item']"):
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

    def _parse_product_card(self, card: BeautifulSoup) -> Optional[dict]:
        """解析单个识货商品卡片"""
        title_el = card.select_one("[class*='title'], [class*='name'], h3, h4")
        title = title_el.get_text(strip=True) if title_el else ""

        price = 0.0
        price_el = card.select_one("[class*='price']")
        if price_el:
            price = self._safe_float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)))

        img_el = card.select_one("img")
        image_url = (img_el.get("src") or img_el.get("data-src") or "") if img_el else ""

        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            id_match = (
                re.search(r"product/(\d+)", href) or re.search(r"productId=(\d+)", href)
                or re.search(r"detail/(\d+)", href) or re.search(r"id=(\d+)", href)
            )
            if id_match:
                product_id = id_match.group(1)

        if not title or not price:
            return None
        return {
            "platform": "shihuo", "platform_id": product_id, "title": title,
            "price": price, "original_price": None,
            "image_url": self._fix_image_url(image_url),
            "sales": 0, "rating": 0, "shop_name": "识货",
            "url": f"https://m.shihuo.cn/product/{product_id}" if product_id else "",
            "brand": "", "extra_data": {},
        }

    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """解析识货商品详情页"""
        price = 0.0
        for pat in (r'"price"\s*:\s*"?([\d.]+)"?', r'"minPrice"\s*:\s*"?([\d.]+)"?',
                    r'"lowestPrice"\s*:\s*"?([\d.]+)"?', r'"currentPrice"\s*:\s*"?([\d.]+)"?',
                    r'"sellPrice"\s*:\s*"?([\d.]+)"?'):
            m = re.search(pat, html)
            if m and (p := self._safe_float(m.group(1))) > 0:
                price = p
                break

        title = ""
        for pat in (r'"title"\s*:\s*"([^"]+)"', r'"productName"\s*:\s*"([^"]+)"', r'"name"\s*:\s*"([^"]+)"'):
            m = re.search(pat, html)
            if m:
                title = m.group(1)
                break
        if not title:
            el = BeautifulSoup(html, "lxml").select_one("title, h1, [class*='title'], [class*='name']")
            title = el.get_text(strip=True) if el else f"识货商品 {product_id}"

        if price <= 0:
            return None
        return {
            "platform": "shihuo", "platform_id": product_id, "title": title,
            "price": price, "url": f"https://m.shihuo.cn/product/{product_id}",
            "shop_name": "识货", "extra_data": {},
        }

    async def _wait_for_content(self, page: object) -> None:
        """等待识货页面加载"""
        try:
            await page.wait_for_selector(
                "[class*='product'], [class*='goods'], [class*='card'], [class*='item']",
                timeout=10000,
            )
        except Exception:
            await asyncio.sleep(3)

    # ===== 工具方法 =====

    def _update_cookies(self, resp: httpx.Response) -> None:
        """从响应中更新cookies"""
        for cookie in resp.cookies.jar:
            self._cookies[cookie.name] = cookie.value

    def _extract_price(self, item: dict) -> float:
        """提取价格"""
        for key in ("price", "minPrice", "lowestPrice", "sellPrice", "currentPrice", "showPrice", "finalPrice"):
            val = item.get(key)
            if val is not None and (p := self._safe_float(val)) > 0:
                return p
        return 0.0

    @staticmethod
    def _has_valid_data(item: dict) -> bool:
        """检查商品数据是否包含必要字段"""
        has_title = bool(item.get("title") or item.get("productName") or item.get("name"))
        has_id = bool(item.get("productId") or item.get("id") or item.get("goodsId") or item.get("spuId"))
        return has_title and has_id

    @staticmethod
    def _safe_float(val: object) -> float:
        """安全转换为浮点数"""
        if val is None:
            return 0.0
        try:
            return float(re.sub(r"[^\d.]", "", str(val)))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_sales(val: object) -> int:
        """解析销量字符串（支持 '1.2万+' 格式）"""
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
        """修复图片URL协议"""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url
