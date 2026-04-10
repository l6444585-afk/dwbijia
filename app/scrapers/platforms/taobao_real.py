"""
淘宝真实数据爬虫

数据获取策略（按优先级）:
  1. H5 API 直接调用 (最快, ~0.5s)
  2. 移动端 H5 页面 HTTP 请求 + 解析 (~2s)
  3. Playwright 浏览器渲染 (兜底, ~5-8s)

目标页面:
  - 搜索: https://s.m.taobao.com/h5?q={keyword}
  - 详情: https://h5.m.taobao.com/awp/core/detail.htm?id={id}
"""
import asyncio
import re
import json
import time
from typing import Optional
from loguru import logger

import httpx
from bs4 import BeautifulSoup

from app.scrapers.platforms.base import RealBaseScraper
from app.scrapers.engine.fingerprint import FingerprintGenerator
from config.settings import settings


class TaobaoRealScraper(RealBaseScraper):
    platform = "taobao"

    def __init__(self):
        super().__init__()
        self._cookies: dict = {}

    # ===== URL 构造 =====

    def _get_search_url(self, keyword: str, page: int) -> str:
        """淘宝移动端搜索页"""
        offset = (page - 1) * 20
        return f"https://s.m.taobao.com/h5?q={keyword}&page={page}&from=mallfp&event_submit_do_new_search_auction=1&_input_charset=utf-8"

    def _get_detail_url(self, product_id: str) -> str:
        """淘宝移动端商品详情页"""
        return f"https://h5.m.taobao.com/awp/core/detail.htm?id={product_id}"

    # ===== API 直接调用（最快） =====

    async def _try_api_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        尝试调用淘宝H5 API

        淘宝 mtop API 需要签名，每次请求需要:
        - 有效的 cookie (_m_h5_tk, _m_h5_tk_enc)
        - 根据 token + timestamp + appKey + data 计算的 sign
        """
        # 如果配置了官方 API Key，使用官方接口
        if settings.TAOBAO_API_KEY and settings.TAOBAO_API_URL:
            return await self._call_official_api(keyword, page)

        # 尝试 mtop H5 API
        return await self._try_mtop_search(keyword, page)

    async def _call_official_api(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        调用淘宝官方开放平台 API

        ================================================
        需要在 .env 配置:
          TAOBAO_API_KEY=你的AppKey
          TAOBAO_API_SECRET=你的AppSecret
          TAOBAO_API_URL=https://eco.taobao.com/router/rest
        ================================================
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                params = {
                    "app_key": settings.TAOBAO_API_KEY,
                    "method": "taobao.tbk.item.get",
                    "format": "json",
                    "v": "2.0",
                    "q": keyword,
                    "page_no": page,
                    "page_size": 20,
                }
                # 签名逻辑需根据实际API文档实现
                resp = await client.get(settings.TAOBAO_API_URL, params=params)
                data = resp.json()
                items_raw = (
                    data.get("tbk_item_get_response", {})
                    .get("results", {})
                    .get("n_tbk_item", [])
                )
                return [
                    {
                        "platform": "taobao",
                        "platform_id": str(item.get("num_iid", "")),
                        "title": item.get("title", ""),
                        "price": float(item.get("zk_final_price", 0)),
                        "original_price": float(item.get("reserve_price", 0)),
                        "image_url": item.get("pict_url", ""),
                        "sales": int(item.get("volume", 0)),
                        "shop_name": item.get("nick", ""),
                        "url": item.get("item_url", ""),
                        "category": item.get("cat_name", ""),
                    }
                    for item in items_raw
                ]
        except Exception as e:
            logger.debug(f"[淘宝] 官方API调用失败: {e}")
            return None

    async def _try_mtop_search(self, keyword: str, page: int) -> Optional[list[dict]]:
        """
        尝试通过 mtop H5 API 搜索

        mtop API 签名流程:
        1. 先访问H5页面获取 _m_h5_tk cookie（包含token）
        2. sign = md5(token + '&' + timestamp + '&' + appKey + '&' + data)
        3. 带签名发起API请求
        """
        try:
            fp = self.fp_gen.generate(mobile=True)
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                # Step 1: 获取 token cookie
                if not self._cookies.get("_m_h5_tk"):
                    init_resp = await client.get(
                        "https://h5.m.taobao.com",
                        headers=fp.headers,
                    )
                    for cookie in init_resp.cookies.jar:
                        self._cookies[cookie.name] = cookie.value

                token = self._cookies.get("_m_h5_tk", "")
                if not token:
                    return None

                token_part = token.split("_")[0] if "_" in token else token
                t = str(int(time.time() * 1000))
                app_key = "12574478"

                # Step 2: 构造请求数据
                data_obj = {"q": keyword, "page": page, "n": 20, "sort": "default"}
                data_str = json.dumps(data_obj, separators=(",", ":"))

                # Step 3: 计算签名
                import hashlib
                sign_str = f"{token_part}&{t}&{app_key}&{data_str}"
                sign = hashlib.md5(sign_str.encode()).hexdigest()

                # Step 4: 发起请求
                api_url = "https://h5api.m.taobao.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/"
                params = {
                    "appKey": app_key,
                    "t": t,
                    "sign": sign,
                    "api": "mtop.relationrecommend.WirelessRecommend.recommend",
                    "v": "2.0",
                    "type": "jsonp",
                    "dataType": "jsonp",
                    "data": data_str,
                }

                resp = await client.get(
                    api_url,
                    params=params,
                    headers=fp.headers,
                    cookies=self._cookies,
                )

                # 解析 JSONP
                text = resp.text
                json_match = re.search(r"mtopjsonp\d*\((.*)\)", text)
                if json_match:
                    result = json.loads(json_match.group(1))
                else:
                    result = json.loads(text)

                # 更新 cookie
                for cookie in resp.cookies.jar:
                    self._cookies[cookie.name] = cookie.value

                # 解析数据
                items_data = (
                    result.get("data", {})
                    .get("itemsArray", [])
                )

                if not items_data:
                    return None

                return [self._normalize_api_item(item) for item in items_data if item.get("title")]

        except Exception as e:
            logger.debug(f"[淘宝] mtop API 失败: {e}")
            return None

    def _normalize_api_item(self, item: dict) -> dict:
        """标准化API返回的商品数据"""
        price = 0
        for key in ("price", "zk_final_price", "reservePrice", "priceShow"):
            val = item.get(key)
            if val:
                try:
                    # 处理 "¥99.00" 或 "99.00" 格式
                    price = float(re.sub(r"[^\d.]", "", str(val)))
                    break
                except (ValueError, TypeError):
                    continue

        return {
            "platform": "taobao",
            "platform_id": str(item.get("item_id", item.get("nid", item.get("itemId", "")))),
            "title": item.get("title", "").strip(),
            "price": price,
            "original_price": self._safe_float(item.get("originalPrice", item.get("reservePrice"))),
            "image_url": self._fix_image_url(item.get("pic", item.get("pic_path", ""))),
            "sales": self._parse_sales(item.get("realSales", item.get("sales", "0"))),
            "rating": self._safe_float(item.get("rating", 0)),
            "shop_name": item.get("shopName", item.get("nick", "")),
            "url": f"https://item.taobao.com/item.htm?id={item.get('item_id', item.get('nid', ''))}",
            "category": item.get("category", ""),
            "brand": item.get("brandName", ""),
        }

    # ===== HTML 解析 =====

    def _parse_search_html(self, html: str, keyword: str) -> list[dict]:
        """
        解析淘宝移动端搜索页 HTML

        淘宝H5页面的数据通常嵌在:
        1. <script> 标签中的 JSON 数据 (g_page_config / g_srp_loadCss_,etc)
        2. 页面DOM元素中
        """
        items = []

        # 策略1: 从嵌入的 JSON 中提取数据
        json_items = self._extract_json_data(html)
        if json_items:
            return json_items

        # 策略2: 从 HTML DOM 解析
        soup = BeautifulSoup(html, "lxml")
        return self._parse_search_dom(soup, keyword)

    def _extract_json_data(self, html: str) -> list[dict]:
        """从页面嵌入的 JavaScript 中提取商品 JSON 数据"""
        items = []

        # 匹配各种嵌入JSON数据的模式
        patterns = [
            r"g_page_config\s*=\s*(\{.*?\})\s*;",
            r"g_srp_loadCss_,?\s*(\{.*?\})\s*[;\)]",
            r'"itemsArray"\s*:\s*(\[.*?\])',
            r'"auctions"\s*:\s*(\[.*?\])',
            r'"listItem"\s*:\s*(\[.*?\])',
            r'window\.__INITIAL_DATA__\s*=\s*(\{.*?\});',
            r'"items"\s*:\s*(\[.*?\])\s*[,}]',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)

                    # 根据数据结构提取商品列表
                    item_list = []
                    if isinstance(data, list):
                        item_list = data
                    elif isinstance(data, dict):
                        for key in ("itemsArray", "auctions", "listItem", "items", "data"):
                            if key in data:
                                candidate = data[key]
                                if isinstance(candidate, list):
                                    item_list = candidate
                                    break
                                elif isinstance(candidate, dict) and "items" in candidate:
                                    item_list = candidate["items"]
                                    break

                    for raw in item_list:
                        if not isinstance(raw, dict):
                            continue
                        if not raw.get("title") and not raw.get("raw_title"):
                            continue
                        try:
                            items.append(self._normalize_api_item(raw))
                        except Exception:
                            continue

                except (json.JSONDecodeError, TypeError):
                    continue

        return items

    def _parse_search_dom(self, soup: BeautifulSoup, keyword: str) -> list[dict]:
        """从DOM元素解析商品列表"""
        items = []
        seen_ids: set[str] = set()

        # 淘宝H5搜索结果选择器（按精确度排序）
        selectors = [
            "[class*='doubleCardWrapper']",
            "[class*='DoubleCard--doubleCard']",
            "div[data-item]",
            ".list-item",
        ]

        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if len(cards) >= 2:
                break

        for card in cards:
            try:
                item = self._parse_item_card(card)
                if item and item.get("price", 0) > 0:
                    pid = item.get("platform_id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        items.append(item)
            except Exception:
                continue

        return items

    def _parse_item_card(self, card) -> Optional[dict]:
        """解析单个商品卡片（适配淘宝 DoubleCard 组件）"""
        # 标题: Title--title 组件
        title_el = card.select_one("[class*='Title--title'], [class*='title'], h3")
        title = title_el.get_text(strip=True) if title_el else ""

        # 价格: 分为整数部分(priceInt)和小数部分(priceFloat)
        price = 0
        price_int_el = card.select_one("[class*='Price--priceInt']")
        price_float_el = card.select_one("[class*='Price--priceFloat']")
        if price_int_el and price_float_el:
            int_part = re.sub(r"[^\d]", "", price_int_el.get_text(strip=True))
            float_part = re.sub(r"[^\d]", "", price_float_el.get_text(strip=True))
            try:
                price = float(f"{int_part}.{float_part}")
            except ValueError:
                pass
        if price == 0:
            # 兜底：找单一价格元素
            price_el = card.select_one("[class*='Price--price'], [class*='price']")
            if price_el:
                price_text = price_el.get_text(strip=True)
                price = self._safe_float(re.sub(r"[^\d.]", "", price_text.split("人")[0]))

        # 图片: MainPic 组件
        img_el = card.select_one("[class*='MainPic--mainPic'], img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        # 商品ID: 从链接的 id= 参数提取
        product_id = ""
        link_el = card.select_one("a[href]")
        if link_el:
            href = link_el.get("href", "")
            id_match = re.search(r"id=(\d+)", href)
            if id_match:
                product_id = id_match.group(1)
        if not product_id:
            product_id = card.get("data-item-id", card.get("data-id", ""))

        # 销量: realSales 组件
        sales = 0
        sales_el = card.select_one("[class*='Price--realSales'], [class*='realSales']")
        if sales_el:
            sales = self._parse_sales(sales_el.get_text(strip=True))

        # 店铺名: 最后的文字 span
        shop_name = ""
        all_spans = card.select("span")
        for span in reversed(all_spans):
            cls = span.get("class", [])
            cls_str = " ".join(cls) if isinstance(cls, list) else str(cls)
            text = span.get_text(strip=True)
            if text and "Price" not in cls_str and "rax-text" not in cls_str:
                shop_name = text
                break

        if not title or not price:
            return None

        return {
            "platform": "taobao",
            "platform_id": str(product_id),
            "title": title,
            "price": price,
            "original_price": None,
            "image_url": self._fix_image_url(image_url),
            "sales": sales,
            "rating": 0,
            "shop_name": shop_name,
            "url": f"https://item.taobao.com/item.htm?id={product_id}" if product_id else "",
        }

    # ===== 详情页解析 =====

    def _parse_detail_html(self, html: str, product_id: str) -> Optional[dict]:
        """解析淘宝商品详情页"""
        # 从嵌入JSON提取
        patterns = [
            r'"price"\s*:\s*"?([\d.]+)"?',
            r'"reservePrice"\s*:\s*"?([\d.]+)"?',
            r'"promPrice"\s*:\s*\{[^}]*"price"\s*:\s*"?([\d.]+)"?',
        ]

        price = 0
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                price = self._safe_float(m.group(1))
                if price > 0:
                    break

        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', html)
        title = title_match.group(1) if title_match else ""

        img_match = re.search(r'"images"\s*:\s*\["([^"]+)"', html)
        image_url = img_match.group(1) if img_match else ""

        if not title:
            soup = BeautifulSoup(html, "lxml")
            title_el = soup.select_one("title, h1, [class*='title']")
            title = title_el.get_text(strip=True) if title_el else f"淘宝商品 {product_id}"

        if price <= 0:
            return None

        return {
            "platform": "taobao",
            "platform_id": product_id,
            "title": title,
            "price": price,
            "image_url": self._fix_image_url(image_url),
            "url": f"https://item.taobao.com/item.htm?id={product_id}",
        }

    async def _wait_for_content(self, page):
        """等待淘宝页面关键内容加载（DoubleCard 组件渲染）"""
        try:
            await page.wait_for_selector(
                "[class*='doubleCardWrapper'], [class*='DoubleCard']",
                timeout=15000,
            )
            await asyncio.sleep(2)  # 等更多卡片渲染
        except Exception:
            await asyncio.sleep(3)

    # ===== 工具方法 =====

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
        s = str(val).lower().replace(",", "").replace("+", "")
        m = re.search(r"([\d.]+)", s)
        if not m:
            return 0
        num = float(m.group(1))
        if "万" in str(val) or "w" in str(val):
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
