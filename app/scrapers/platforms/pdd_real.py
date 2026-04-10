"""
拼多多(Pinduoduo)真实数据爬虫

数据获取策略（按优先级）:
  1. 拼多多 H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://mobile.yangkeduo.com/search_result.html?search_key={keyword}
  - 详情: https://mobile.yangkeduo.com/goods.html?goods_id={product_id}

拼多多特有逻辑:
  - 团购价(group_price) vs 单买价(single_price)，主价格取团购价
  - 页面数据嵌入在 window.__INIT_DATA__ / rawData 等全局变量中
"""
import asyncio
import re
import json
from typing import Optional
from loguru import logger

import httpx
from bs4 import BeautifulSoup

from app.scrapers.platforms.base import RealBaseScraper
from app.scrapers.engine.fingerprint import FingerprintGenerator
from config.settings import settings


class PddRealScraper(RealBaseScraper):
    platform = "pdd"

    def __init__(self) -> None:
        super().__init__()
        self._cookies: dict[str, str] = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """拼多多移动端搜索页"""
        return (
            f"https://mobile.yangkeduo.com/search_result.html"
            f"?search_key={keyword}&page={page}"
        )

    def _get_detail_url(self, product_id: str) -> str:
        """拼多多商品详情页"""
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={product_id}"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(
        self, keyword: str, page: int
    ) -> Optional[list[dict]]:
        """
        尝试调用拼多多 H5 API 搜索

        优先使用配置的第三方API，否则走H5接口
        """
        # 优先使用配置的 API
        if settings.PDD_API_KEY and settings.PDD_API_URL:
            return await self._call_configured_api(keyword, page)

        # 尝试拼多多 H5 API
        return await self._try_h5_api_search(keyword, page)

    async def _call_configured_api(
        self, keyword: str, page: int
    ) -> Optional[list[dict]]:
        """
        调用配置的拼多多 API（官方合作/第三方）

        ================================================
        在 .env 配置:
          PDD_API_KEY=你的API密钥
          PDD_API_SECRET=你的Secret
          PDD_API_URL=API基础地址
        ================================================
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {
                    "Authorization": f"Bearer {settings.PDD_API_KEY}",
                    "Content-Type": "application/json",
                }
                resp = await client.get(
                    f"{settings.PDD_API_URL}/search",
                    params={"keyword": keyword, "page": page, "limit": 20},
                    headers=headers,
                )
                data = resp.json()
                items_raw = data.get("data", {}).get(
                    "list", data.get("list", [])
                )
                return [
                    self._normalize_api_item(item)
                    for item in items_raw
                    if item.get("goodsName") or item.get("title")
                ]
        except Exception as e:
            logger.debug(f"[拼多多] 配置API调用失败: {e}")
            return None

    async def _try_h5_api_search(
        self, keyword: str, page: int
    ) -> Optional[list[dict]]:
        """
        尝试调用拼多多 H5 API

        拼多多 H5 API 端点:
        - 搜索: GET https://apiv2.yangkeduo.com/search
               POST https://api.yangkeduo.com/search
        """
        endpoints = [
            ("GET", "https://apiv2.yangkeduo.com/search"),
            ("GET", "https://api.yangkeduo.com/search"),
        ]

        fp = self.fp_gen.generate(mobile=True)
        headers = {
            **fp.headers,
            "Referer": "https://mobile.yangkeduo.com/",
            "Origin": "https://mobile.yangkeduo.com",
        }

        params = {
            "search_key": keyword,
            "page": str(page),
            "size": "20",
            "list_id": "",
            "flip": "",
        }

        for method, url in endpoints:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    if method == "GET":
                        resp = await client.get(
                            url,
                            params=params,
                            headers=headers,
                            cookies=self._cookies,
                        )
                    else:
                        resp = await client.post(
                            url,
                            json=params,
                            headers=headers,
                            cookies=self._cookies,
                        )

                    # 更新cookies
                    for cookie in resp.cookies.jar:
                        self._cookies[cookie.name] = cookie.value

                    if resp.status_code != 200:
                        continue

                    data = resp.json()

                    # 拼多多API返回格式多种
                    item_list = (
                        data.get("data", {}).get("goods_list", [])
                        or data.get("data", {}).get("list", [])
                        or data.get("goods_list", [])
                        or data.get("items", [])
                        or []
                    )

                    if not item_list:
                        continue

                    items = [
                        self._normalize_api_item(item)
                        for item in item_list
                        if self._has_valid_data(item)
                    ]
                    if items:
                        return items

            except Exception as e:
                logger.debug(f"[拼多多] H5 API 搜索失败 ({url}): {e}")
                continue

        return None

    async def _try_api_detail(self, product_id: str) -> Optional[dict]:
        """尝试通过 API 获取商品详情"""
        endpoints = [
            f"https://apiv2.yangkeduo.com/goods/{product_id}",
            f"https://api.yangkeduo.com/goods/{product_id}",
        ]

        fp = self.fp_gen.generate(mobile=True)
        headers = {
            **fp.headers,
            "Referer": (
                f"https://mobile.yangkeduo.com/goods.html"
                f"?goods_id={product_id}"
            ),
            "Origin": "https://mobile.yangkeduo.com",
        }

        for url in endpoints:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        url,
                        headers=headers,
                        cookies=self._cookies,
                    )

                    for cookie in resp.cookies.jar:
                        self._cookies[cookie.name] = cookie.value

                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    detail = data.get("data", data)

                    if not detail:
                        continue

                    result = self._normalize_detail(detail, product_id)
                    if result and result.get("price", 0) > 0:
                        return result

            except Exception as e:
                logger.debug(f"[拼多多] API 详情获取失败 ({url}): {e}")
                continue

        return None

    # ===== 数据标准化 =====

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化拼多多API搜索结果"""
        # 价格处理 - 拼多多价格通常以分为单位
        group_price = self._extract_group_price(item)
        single_price = self._extract_single_price(item)
        # 主价格取团购价
        price = group_price if group_price > 0 else single_price

        # 商品ID
        goods_id = str(
            item.get("goods_id", "")
            or item.get("goodsId", "")
            or item.get("id", "")
        )

        # 图片
        image = (
            item.get("hd_thumb_url", "")
            or item.get("thumb_url", "")
            or item.get("image_url", "")
            or item.get("imgUrl", "")
            or item.get("image", "")
        )

        # 销量
        sales = self._parse_sales(
            item.get("sales_tip", "")
            or item.get("cnt", "")
            or item.get("salesTip", "")
            or item.get("sales", "0")
        )

        # 店铺名
        shop_name = (
            item.get("mall_name", "")
            or item.get("mallName", "")
            or "拼多多"
        )

        # 标题
        title = (
            item.get("goods_name", "")
            or item.get("goodsName", "")
            or item.get("title", "")
        ).strip()

        return {
            "platform": "pdd",
            "platform_id": goods_id,
            "title": title,
            "price": price,
            "group_price": group_price,
            "single_price": single_price,
            "original_price": self._safe_float(
                item.get("market_price", item.get("marketPrice"))
            ),
            "image_url": self._fix_image_url(image),
            "sales": sales,
            "rating": self._safe_float(
                item.get("avg_desc", item.get("score", 0))
            ),
            "shop_name": shop_name,
            "url": (
                f"https://mobile.yangkeduo.com/goods.html"
                f"?goods_id={goods_id}"
            ),
            "brand": item.get("brand_name", item.get("brandName", "")),
            "category": item.get("cat_name", item.get("categoryName", "")),
            "extra_data": {
                "coupon_discount": self._safe_float(
                    item.get("coupon_discount", 0)
                ),
                "has_coupon": bool(item.get("has_coupon", False)),
                "group_type": "拼团",
            },
        }

    def _normalize_detail(self, detail: dict, product_id: str) -> dict:
        """标准化拼多多商品详情"""
        info = detail.get("goods", detail)

        group_price = self._extract_group_price(info)
        single_price = self._extract_single_price(info)
        price = group_price if group_price > 0 else single_price

        # SKU最低价
        sku_list = info.get("sku", info.get("skus", []))
        if sku_list:
            prices = []
            for sku in sku_list:
                p = self._extract_group_price(sku)
                if p <= 0:
                    p = self._safe_float(sku.get("price", 0))
                    if p > 100:
                        p /= 100  # 分 → 元
                if p > 0:
                    prices.append(p)
            if prices:
                price = min(prices)

        title = (
            info.get("goods_name", "")
            or info.get("goodsName", "")
            or info.get("title", "")
            or f"拼多多商品 {product_id}"
        )

        image = (
            info.get("hd_thumb_url", "")
            or info.get("thumb_url", "")
            or info.get("image_url", "")
            or ""
        )

        return {
            "platform": "pdd",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "group_price": group_price,
            "single_price": single_price,
            "original_price": self._safe_float(
                info.get("market_price", info.get("marketPrice"))
            ),
            "image_url": self._fix_image_url(image),
            "sales": self._parse_sales(info.get("sales_tip", "0")),
            "rating": self._safe_float(info.get("avg_desc", 0)),
            "shop_name": info.get("mall_name", "拼多多"),
            "url": (
                f"https://mobile.yangkeduo.com/goods.html"
                f"?goods_id={product_id}"
            ),
            "brand": info.get("brand_name", ""),
            "extra_data": {
                "coupon_discount": self._safe_float(
                    info.get("coupon_discount", 0)
                ),
                "has_coupon": bool(info.get("has_coupon", False)),
                "sku_count": len(sku_list) if sku_list else 0,
                "group_type": "拼团",
            },
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:
        """解析拼多多搜索页HTML"""
        # 策略1: 从嵌入JSON提取（拼多多H5页面数据嵌在全局变量中）
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items

        # 策略2: DOM解析兜底
        soup = BeautifulSoup(html, "lxml")
        return self._parse_search_dom(soup)

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面嵌入JavaScript中提取商品数据"""
        items: list[dict] = []

        # 拼多多H5页面常见的数据嵌入模式
        patterns = [
            r"window\.__INIT_DATA__\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"window\.rawData\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"window\.__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>",
            r"window\.__DATA__\s*=\s*(\{.*?\})\s*;",
            r'"goods_list"\s*:\s*(\[.*?\])\s*[,}]',
            r'"list"\s*:\s*(\[.*?\])\s*,\s*"(?:total|page|flip)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
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

    def _dig_product_list(self, data: object) -> list:
        """递归查找商品列表"""
        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict) and any(
                k in data[0]
                for k in (
                    "goods_name", "goodsName", "goods_id",
                    "goodsId", "title", "price",
                )
            ):
                return data

        if isinstance(data, dict):
            # 拼多多常见的数据键名
            keys = (
                "goods_list", "goodsList", "list", "items",
                "data", "result", "props", "pageProps", "ssrData",
            )
            for key in keys:
                if key in data:
                    result = self._dig_product_list(data[key])
                    if result:
                        return result
        return []

    def _parse_search_dom(self, soup: BeautifulSoup) -> list[dict]:
        """DOM解析拼多多搜索结果"""
        items: list[dict] = []

        # 拼多多H5页面常见的卡片选择器
        selectors = [
            "[class*='goods']",
            "[class*='product']",
            "[class*='card']",
            "[class*='item']",
        ]

        cards: list = []
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

    def _parse_product_card(self, card: BeautifulSoup) -> Optional[dict]:
        """解析单个拼多多商品卡片"""
        # 标题
        title_el = card.select_one(
            "[class*='title'], [class*='name'], h3, h4"
        )
        title = title_el.get_text(strip=True) if title_el else ""

        # 价格
        price = 0.0
        price_el = card.select_one("[class*='price']")
        if price_el:
            price_text = price_el.get_text(strip=True)
            price = self._safe_float(re.sub(r"[^\d.]", "", price_text))

        # 图片
        img_el = card.select_one("img")
        image_url = ""
        if img_el:
            image_url = (
                img_el.get("src")
                or img_el.get("data-src")
                or img_el.get("data-lazy-src")
                or ""
            )

        # 商品ID - 从链接中提取
        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            id_match = (
                re.search(r"goods_id=(\d+)", href)
                or re.search(r"goods/(\d+)", href)
            )
            if id_match:
                product_id = id_match.group(1)

        if not title or not price:
            return None

        return {
            "platform": "pdd",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "group_price": price,
            "single_price": 0,
            "original_price": None,
            "image_url": self._fix_image_url(image_url),
            "sales": 0,
            "rating": 0,
            "shop_name": "拼多多",
            "url": (
                f"https://mobile.yangkeduo.com/goods.html"
                f"?goods_id={product_id}"
                if product_id
                else ""
            ),
            "brand": "",
            "extra_data": {"group_type": "拼团"},
        }

    def _parse_detail_html(
        self, html: str, product_id: str
    ) -> Optional[dict]:
        """解析拼多多商品详情页"""
        # 策略1: 从嵌入JSON提取完整数据
        detail = self._extract_detail_json(html, product_id)
        if detail and detail.get("price", 0) > 0:
            return detail

        # 策略2: 正则直取价格和标题
        price = self._regex_extract_price(html)
        title = self._regex_extract_title(html)

        # 策略3: DOM兜底
        if not title:
            soup = BeautifulSoup(html, "lxml")
            title_el = soup.select_one(
                "title, h1, [class*='title'], [class*='name']"
            )
            title = (
                title_el.get_text(strip=True)
                if title_el
                else f"拼多多商品 {product_id}"
            )

        if price <= 0:
            return None

        return {
            "platform": "pdd",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "group_price": price,
            "single_price": 0,
            "url": (
                f"https://mobile.yangkeduo.com/goods.html"
                f"?goods_id={product_id}"
            ),
            "shop_name": "拼多多",
            "extra_data": {"group_type": "拼团"},
        }

    def _extract_detail_json(
        self, html: str, product_id: str
    ) -> Optional[dict]:
        """从详情页HTML中提取嵌入的JSON数据"""
        patterns = [
            r"window\.__INIT_DATA__\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"window\.rawData\s*=\s*(\{.*?\})\s*;?\s*</script>",
            r"window\.__NEXT_DATA__\s*=\s*(\{.*?\})\s*</script>",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    # 尝试从嵌套结构中找到商品数据
                    goods = self._dig_goods_detail(data)
                    if goods:
                        return self._normalize_detail(
                            {"goods": goods}, product_id
                        )
                except (json.JSONDecodeError, TypeError):
                    continue

        return None

    def _dig_goods_detail(self, data: object) -> Optional[dict]:
        """递归查找商品详情数据"""
        if not isinstance(data, dict):
            return None

        # 直接包含商品字段
        if any(
            k in data
            for k in ("goods_name", "goodsName", "goods_id", "goodsId")
        ):
            return data

        # 递归搜索常见键
        for key in (
            "goods", "goodsDetail", "store", "data",
            "result", "initData", "pageData",
        ):
            if key in data:
                result = self._dig_goods_detail(data[key])
                if result:
                    return result

        return None

    def _regex_extract_price(self, html: str) -> float:
        """正则提取价格"""
        # 团购价优先
        price_patterns = [
            r'"group_price"\s*:\s*"?([\d.]+)"?',
            r'"groupPrice"\s*:\s*"?([\d.]+)"?',
            r'"min_group_price"\s*:\s*"?([\d.]+)"?',
            r'"price"\s*:\s*"?([\d.]+)"?',
            r'"minPrice"\s*:\s*"?([\d.]+)"?',
            r'"min_normal_price"\s*:\s*"?([\d.]+)"?',
        ]

        for pat in price_patterns:
            m = re.search(pat, html)
            if m:
                price = self._safe_float(m.group(1))
                if price > 0:
                    # 拼多多价格如果大于10000可能是分为单位
                    if price > 100000:
                        price /= 100
                    return price
        return 0

    def _regex_extract_title(self, html: str) -> str:
        """正则提取标题"""
        title_patterns = [
            r'"goods_name"\s*:\s*"([^"]+)"',
            r'"goodsName"\s*:\s*"([^"]+)"',
            r'"title"\s*:\s*"([^"]+)"',
        ]
        for pat in title_patterns:
            m = re.search(pat, html)
            if m:
                return m.group(1)
        return ""

    async def _wait_for_content(self, page: object) -> None:
        """等待拼多多页面加载"""
        try:
            await page.wait_for_selector(
                "[class*='goods'], [class*='product'], "
                "[class*='card'], [class*='item']",
                timeout=10000,
            )
        except Exception:
            await asyncio.sleep(3)

    # ===== 价格提取工具 =====

    def _extract_group_price(self, item: dict) -> float:
        """提取团购价 - 拼多多核心价格"""
        for key in (
            "group_price", "groupPrice", "min_group_price",
            "minGroupPrice", "price",
        ):
            val = item.get(key)
            if val is not None:
                p = self._safe_float(val)
                if p > 0:
                    # 大于10万可能是分为单位
                    if p > 100000:
                        p /= 100
                    return p
        return 0

    def _extract_single_price(self, item: dict) -> float:
        """提取单买价"""
        for key in (
            "single_price", "singlePrice", "min_normal_price",
            "normalPrice", "market_price", "marketPrice",
        ):
            val = item.get(key)
            if val is not None:
                p = self._safe_float(val)
                if p > 0:
                    if p > 100000:
                        p /= 100
                    return p
        return 0

    # ===== 通用工具方法 =====

    @staticmethod
    def _has_valid_data(item: dict) -> bool:
        """检查商品数据是否有效"""
        has_name = bool(
            item.get("goods_name")
            or item.get("goodsName")
            or item.get("title")
        )
        has_id = bool(
            item.get("goods_id")
            or item.get("goodsId")
            or item.get("id")
        )
        return has_name and has_id

    @staticmethod
    def _safe_float(val: object) -> float:
        """安全转换为浮点数"""
        if val is None:
            return 0
        try:
            return float(re.sub(r"[^\d.]", "", str(val)))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_sales(val: object) -> int:
        """解析销量文本（支持'10万+'等格式）"""
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
        """修复图片URL"""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url
