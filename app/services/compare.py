"""
智能比价服务 - 核心比较逻辑
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scrapers.sdk.client import scraper_client
from app.models.product import Product, PriceHistory


class CompareService:
    """跨平台比价服务"""

    def __init__(self):
        # 兼容旧接口（用于单元测试等场景）
        self.taobao = scraper_client.scrapers["taobao"]
        self.dewu = scraper_client.scrapers["dewu"]

    async def search_and_compare(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """
        同时搜索两个平台并对比价格（使用真实爬虫）
        """
        sdk_result = await scraper_client.search(keyword, page, page_size)

        tb_result = sdk_result["platforms"].get("taobao", {})
        dw_result = sdk_result["platforms"].get("dewu", {})

        tb_items = tb_result.get("items", [])
        dw_items = dw_result.get("items", [])

        # 尝试匹配相同/相似商品
        matched = self._match_products(tb_items, dw_items)

        # 计算比价统计
        stats = self._calc_stats(tb_items, dw_items, matched)

        return {
            "keyword": keyword,
            "taobao": {"items": tb_items, "total": tb_result.get("total", 0) if isinstance(tb_result, dict) else 0},
            "dewu": {"items": dw_items, "total": dw_result.get("total", 0) if isinstance(dw_result, dict) else 0},
            "matched": matched,
            "stats": stats,
        }

    def _match_products(self, tb_items: list, dw_items: list) -> list:
        """
        匹配两个平台的相似商品

        匹配策略：品牌 + 关键词相似度
        """
        matched = []
        used_dw = set()

        for tb in tb_items:
            best_match = None
            best_score = 0

            for j, dw in enumerate(dw_items):
                if j in used_dw:
                    continue
                score = self._similarity_score(tb, dw)
                if score > best_score and score > 0.3:
                    best_score = score
                    best_match = (j, dw)

            if best_match:
                j, dw = best_match
                used_dw.add(j)
                diff = tb["price"] - dw["price"]
                cheaper = "taobao" if diff < 0 else "dewu" if diff > 0 else "same"
                matched.append({
                    "taobao": tb,
                    "dewu": dw,
                    "price_diff": round(abs(diff), 2),
                    "cheaper_platform": cheaper,
                    "save_percent": round(abs(diff) / max(tb["price"], dw["price"]) * 100, 1) if max(tb["price"], dw["price"]) > 0 else 0,
                    "similarity": round(best_score, 2),
                })

        # 按价差百分比排序（差价大的排前面）
        matched.sort(key=lambda x: x["save_percent"], reverse=True)
        return matched

    def _similarity_score(self, item_a: dict, item_b: dict) -> float:
        """计算两个商品的相似度 (0~1)"""
        score = 0.0

        # 品牌匹配 (权重高)
        brand_a = (item_a.get("brand") or "").lower()
        brand_b = (item_b.get("brand") or "").lower()
        if brand_a and brand_b and brand_a == brand_b:
            score += 0.4

        # 标题关键词匹配
        title_a = set(item_a.get("title", "").lower().split())
        title_b = set(item_b.get("title", "").lower().split())
        if title_a and title_b:
            common = title_a & title_b
            total = title_a | title_b
            if total:
                score += 0.4 * len(common) / len(total)

        # 价格接近度 (价格差异在30%以内加分)
        price_a = item_a.get("price", 0)
        price_b = item_b.get("price", 0)
        if price_a > 0 and price_b > 0:
            ratio = min(price_a, price_b) / max(price_a, price_b)
            if ratio > 0.7:
                score += 0.2 * ratio

        return score

    def _calc_stats(self, tb_items: list, dw_items: list, matched: list) -> dict:
        """计算比价统计数据"""
        tb_avg = sum(i["price"] for i in tb_items) / len(tb_items) if tb_items else 0
        dw_avg = sum(i["price"] for i in dw_items) / len(dw_items) if dw_items else 0

        tb_cheaper_count = sum(1 for m in matched if m["cheaper_platform"] == "taobao")
        dw_cheaper_count = sum(1 for m in matched if m["cheaper_platform"] == "dewu")

        max_save = max((m["price_diff"] for m in matched), default=0)

        return {
            "taobao_avg_price": round(tb_avg, 2),
            "dewu_avg_price": round(dw_avg, 2),
            "taobao_cheaper_count": tb_cheaper_count,
            "dewu_cheaper_count": dw_cheaper_count,
            "matched_count": len(matched),
            "max_save_amount": round(max_save, 2),
            "overall_cheaper": "taobao" if tb_avg < dw_avg else "dewu" if dw_avg < tb_avg else "same",
        }

    async def save_products(self, items: list, db: AsyncSession):
        """保存商品数据到数据库"""
        for item in items:
            existing = await db.execute(
                select(Product).where(
                    Product.platform == item["platform"],
                    Product.platform_id == item["platform_id"],
                )
            )
            product = existing.scalar_one_or_none()

            if product:
                # 更新价格
                old_price = product.price
                product.price = item["price"]
                product.sales = item.get("sales", product.sales)
                product.rating = item.get("rating", product.rating)

                # 如果价格变动，记录历史
                if old_price != item["price"]:
                    history = PriceHistory(
                        product_id=product.id,
                        platform=item["platform"],
                        price=item["price"],
                    )
                    db.add(history)
            else:
                product = Product(
                    title=item.get("title", ""),
                    platform=item["platform"],
                    platform_id=item["platform_id"],
                    url=item.get("url", ""),
                    image_url=item.get("image_url", ""),
                    price=item["price"],
                    original_price=item.get("original_price"),
                    sales=item.get("sales", 0),
                    rating=item.get("rating", 0),
                    shop_name=item.get("shop_name", ""),
                    category=item.get("category", ""),
                    brand=item.get("brand", ""),
                    specs=item.get("specs"),
                    extra_data=item.get("extra_data"),
                )
                db.add(product)
                await db.flush()

                # 首次记录价格历史
                history = PriceHistory(
                    product_id=product.id,
                    platform=item["platform"],
                    price=item["price"],
                )
                db.add(history)

        await db.commit()
