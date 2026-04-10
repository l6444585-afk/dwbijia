"""
京东真实数据爬虫

数据获取策略（按优先级）:
  1. H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://so.m.jd.com/ware/search.action?keyword={keyword}
  - 详情: https://item.m.jd.com/product/{product_id}.html
"""
import asyncio
import hashlib
import json
import re
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.scrapers.platforms.base import RealBaseScraper
from config.settings import settings


class JdRealScraper(RealBaseScraper):
    platform = "jd"

    def __init__(self) -> None:
        super().__init__()
        self._cookies: dict[str, str] = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """京东移动端搜索页"""
        return f"https://so.m.jd.com/ware/search.action?keyword={keyword}&page={page}&searchFrom=home"

    def _get_detail_url(self, product_id: str) -> str:
        """京东移动端商品详情页"""
        return f"https://item.m.jd.com/product/{product_id}.html"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """优先官方 API，否则尝试 H5 client.action 接口"""
        if settings.JD_API_KEY and settings.JD_API_URL:
            return await self._call_official_api(keyword, page)
        return await self._try_h5_search(keyword, page)

    async def _call_official_api(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        调用京东联盟开放平台 API
        需要在 .env 配置: JD_API_KEY, JD_API_SECRET, JD_API_URL
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                t = str(int(time.time() * 1000))
                params = {
                    "app_key": settings.JD_API_KEY,
                    "method": "jd.union.open.goods.query",
                    "format": "json",
                    "v": "1.0",
                    "timestamp": t,
                }
                goods_req = {"keyword": keyword, "pageIndex": page, "pageSize": 20}
                params["param_json"] = json.dumps({"goodsReqDTO": goods_req}, separators=(",", ":"))

                # 签名: md5(secret + 按key排序的k+v拼接 + secret)
                sign_parts = sorted(params.items())
                sign_str = settings.JD_API_SECRET + "".join(f"{k}{v}" for k, v in sign_parts) + settings.JD_API_SECRET
                params["sign"] = hashlib.md5(sign_str.encode()).hexdigest().upper()

                resp = await client.get(settings.JD_API_URL, params=params)
                data = resp.json()
                items_raw = data.get("jd_union_open_goods_query_response", {}).get("result", "{}")
                if isinstance(items_raw, str):
                    items_raw = json.loads(items_raw)

                return [
                    {
                        "platform": "jd",
                        "product_id": str(item.get("skuId", "")),
                        "title": item.get("skuName", ""),
                        "price": self._safe_float(
                            item.get("priceInfo", {}).get("lowestCouponPrice")
                            or item.get("priceInfo", {}).get("price")
                        ),
                        "image": self._fix_image_url(
                            item.get("imageInfo", {}).get("imageList", [{}])[0].get("url", "")
                            if item.get("imageInfo", {}).get("imageList")
                            else ""
                        ),
                        "url": item.get("materialUrl", ""),
                    }
                    for item in items_raw.get("data", [])
                ]
        except Exception as e:
            logger.debug(f"[京东] 官方API调用失败: {e}")
            return None

    async def _try_h5_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """通过京东 H5 client.action 接口搜索"""
        try:
            fp = self.fp_gen.generate(mobile=True)
            if not self._cookies:
                await self._init_cookies(fp)

            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                t = str(int(time.time() * 1000))
                body = json.dumps(
                    {"keyword": keyword, "page": str(page), "pagesize": "20", "searchtype": "text"},
                    separators=(",", ":"),
                )
                params = {"functionId": "search", "appid": "wh5", "body": body, "t": t, "loginType": "2"}
                headers = {**fp.headers, "Referer": "https://so.m.jd.com/", "Origin": "https://so.m.jd.com"}

                resp = await client.get(
                    "https://api.m.jd.com/client.action",
                    params=params, headers=headers, cookies=self._cookies,
                )
                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value

                data = resp.json()
                warehouse_list = (
                    data.get("wareList")
                    or data.get("data", {}).get("wareList", [])
                    or data.get("searchResponse", {}).get("wareList", [])
                )
                if not warehouse_list:
                    return None

                return [self._normalize_api_item(item) for item in warehouse_list if item.get("wname") or item.get("title")]
        except Exception as e:
            logger.debug(f"[京东] H5 API 失败: {e}")
            return None

    async def _init_cookies(self, fp) -> None:
        """访问京东移动端首页获取初始 cookie"""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get("https://so.m.jd.com/", headers=fp.headers)
                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value
        except Exception as e:
            logger.debug(f"[京东] 获取初始cookie失败: {e}")

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化 API 返回的商品数据"""
        price = 0.0
        for key in ("jdPrice", "price", "wmPrice", "tpp", "pc"):
            val = item.get(key)
            if val:
                price = self._safe_float(val)
                if price > 0:
                    break

        product_id = str(item.get("wareId") or item.get("skuId") or item.get("itemId") or "")
        title = (item.get("wname") or item.get("title") or item.get("skuName") or "").strip()
        image = item.get("imageurl") or item.get("img") or item.get("pic") or ""

        return {
            "platform": "jd",
            "product_id": product_id,
            "title": title,
            "price": price,
            "image": self._fix_image_url(image),
            "url": f"https://item.m.jd.com/product/{product_id}.html" if product_id else "",
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:  # noqa: ARG002
        """解析京东移动端搜索页，先尝试内嵌 JSON，再 DOM 兜底"""
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items
        return self._parse_search_dom(BeautifulSoup(html, "lxml"))

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面 <script> 中提取商品 JSON 数据"""
        items: list[dict] = []
        patterns = [
            r"window\.__INIT_DATA__\s*=\s*(\{.*?\})\s*;",
            r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;",
            r'"wareList"\s*:\s*(\[.*?\])\s*[,}]',
            r'"itemList"\s*:\s*(\[.*?\])\s*[,}]',
            r'"searchResponse"\s*:\s*(\{.*?\})\s*[,;]',
            r'"commodityList"\s*:\s*(\[.*?\])\s*[,}]',
            r'"goods"\s*:\s*(\[.*?\])\s*[,}]',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, html, re.DOTALL):
                try:
                    data = json.loads(match)
                    for raw in self._dig_item_list(data):
                        if isinstance(raw, dict) and (raw.get("wname") or raw.get("title") or raw.get("skuName")):
                            try:
                                items.append(self._normalize_api_item(raw))
                            except Exception:
                                continue
                except (json.JSONDecodeError, TypeError):
                    continue
        return items

    def _dig_item_list(self, data) -> list:
        """从嵌套 JSON 中挖掘商品列表"""
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("wareList", "itemList", "commodityList", "goods", "data", "searchResponse", "result"):
            if key not in data:
                continue
            val = data[key]
            if isinstance(val, list) and val:
                return val
            if isinstance(val, dict):
                inner = self._dig_item_list(val)
                if inner:
                    return inner
        return []

    def _parse_search_dom(self, soup: BeautifulSoup) -> list[dict]:
        """从 DOM 元素解析商品列表"""
        items: list[dict] = []
        selectors = [
            ".search-result-list .product-item", ".search_prolist_item",
            ".list-item", ".product-list li", ".goods-item",
            "[class*='ware-item']", "[class*='product']",
        ]
        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if len(cards) >= 3:
                break
        for card in cards:
            try:
                item = self._parse_item_card(card)
                if item and item.get("price", 0) > 0:
                    items.append(item)
            except Exception:
                continue
        return items

    def _parse_item_card(self, card) -> Optional[dict]:
        """解析单个商品卡片 DOM"""
        title_el = card.select_one("[class*='title'], [class*='name'], .product-name, h3")
        title = title_el.get_text(strip=True) if title_el else ""

        price = 0.0
        price_el = card.select_one("[class*='price'], .product-price, .price")
        if price_el:
            price = self._safe_float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)))

        img_el = card.select_one("img")
        image = ""
        if img_el:
            image = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-img") or img_el.get("data-original") or ""

        # 商品 ID - 从链接或 data 属性提取
        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            id_match = re.search(r"/product/(\d+)", href) or re.search(r"wareId=(\d+)", href)
            if id_match:
                product_id = id_match.group(1)
        if not product_id:
            product_id = card.get("data-sku") or card.get("data-id") or card.get("data-wareid") or ""

        if not title or price <= 0:
            return None
        return {
            "platform": "jd",
            "product_id": str(product_id),
            "title": title,
            "price": price,
            "image": self._fix_image_url(image),
            "url": f"https://item.m.jd.com/product/{product_id}.html" if product_id else "",
        }

    # ===== 详情页解析 =====

    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """解析京东商品详情页，依次尝试内嵌JSON、正则、DOM"""
        # 策略1: 内嵌 JSON (window.__INIT_DATA__ 等)
        for pattern in (
            r"window\.__INIT_DATA__\s*=\s*(\{.*?\})\s*;",
            r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;",
            r"window\.productConfig\s*=\s*(\{.*?\})\s*;",
        ):
            m = re.search(pattern, html, re.DOTALL)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                detail = self._detail_from_json(data, product_id)
                if detail:
                    return detail
            except (json.JSONDecodeError, TypeError):
                continue

        # 策略2: 正则提取关键字段
        price = 0.0
        for pat in (r'"price"\s*:\s*"?([\d.]+)"?', r'"p"\s*:\s*"?([\d.]+)"?',
                    r'"jdPrice"\s*:\s*"?([\d.]+)"?', r'"wPrice"\s*:\s*"?([\d.]+)"?'):
            m = re.search(pat, html)
            if m:
                price = self._safe_float(m.group(1))
                if price > 0:
                    break

        title_match = re.search(r'"skuName"\s*:\s*"([^"]+)"', html) or re.search(r'"name"\s*:\s*"([^"]+)"', html)
        title = title_match.group(1) if title_match else ""
        img_match = re.search(r'"imagePath"\s*:\s*"([^"]+)"', html) or re.search(r'"img"\s*:\s*"([^"]+)"', html)
        image = img_match.group(1) if img_match else ""

        # 策略3: DOM 兜底取标题
        if not title:
            soup = BeautifulSoup(html, "lxml")
            title_el = soup.select_one("title, h1, .product-name, [class*='sku-name']")
            title = title_el.get_text(strip=True) if title_el else f"京东商品 {product_id}"

        if price <= 0:
            return None
        return {
            "platform": "jd", "product_id": product_id, "title": title,
            "price": price, "image": self._fix_image_url(image),
            "url": f"https://item.m.jd.com/product/{product_id}.html",
        }

    def _detail_from_json(self, data: dict, product_id: str) -> Optional[dict]:
        """从详情页 JSON 数据中提取商品信息"""
        price = 0.0
        price_info = data.get("price") or data.get("priceInfo") or {}
        if isinstance(price_info, dict):
            price = self._safe_float(price_info.get("p") or price_info.get("price") or price_info.get("jdPrice"))
        elif isinstance(price_info, (str, int, float)):
            price = self._safe_float(price_info)

        title = (data.get("skuName") or data.get("name") or data.get("title") or "")
        image = ""
        img_info = data.get("image") or data.get("imageInfo") or {}
        if isinstance(img_info, str):
            image = img_info
        elif isinstance(img_info, dict):
            image = img_info.get("imagePath") or img_info.get("img") or ""

        if not title or price <= 0:
            return None
        return {
            "platform": "jd", "product_id": product_id, "title": title.strip(),
            "price": price, "image": self._fix_image_url(image),
            "url": f"https://item.m.jd.com/product/{product_id}.html",
        }

    async def _wait_for_content(self, page) -> None:
        """等待京东页面关键内容加载"""
        try:
            await page.wait_for_selector(
                "[class*='product'], [class*='ware'], [class*='goods'], [class*='item']",
                timeout=10000,
            )
        except Exception:
            await asyncio.sleep(3)

    # ===== 工具方法 =====

    @staticmethod
    def _safe_float(val) -> float:
        """安全转换为浮点数"""
        if val is None:
            return 0.0
        try:
            return float(re.sub(r"[^\d.]", "", str(val)))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _fix_image_url(url: str) -> str:
        """修正图片URL，补全协议头"""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url
