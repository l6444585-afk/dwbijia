"""
价格监控服务 - 定期检查价格变动，触发提醒
"""
from datetime import datetime
from typing import Optional
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, PriceHistory
from app.models.user import PriceAlert
from app.scrapers.taobao import TaobaoScraper
from app.scrapers.dewu import DewuScraper


class MonitorService:
    """价格监控服务"""

    def __init__(self):
        self.scrapers = {
            "taobao": TaobaoScraper(),
            "dewu": DewuScraper(),
        }

    async def check_price(self, product: Product) -> Optional[float]:
        """检查单个商品的最新价格"""
        scraper = self.scrapers.get(product.platform)
        if not scraper:
            return None

        new_price = await scraper.get_price(product.platform_id)
        return new_price

    async def update_all_prices(self, db: AsyncSession):
        """
        批量更新所有商品价格
        用于定时任务
        """
        result = await db.execute(select(Product))
        products = result.scalars().all()

        updated = 0
        for product in products:
            try:
                new_price = await self.check_price(product)
                if new_price is not None and new_price != product.price:
                    # 记录价格历史
                    history = PriceHistory(
                        product_id=product.id,
                        platform=product.platform,
                        price=new_price,
                    )
                    db.add(history)

                    old_price = product.price
                    product.price = new_price
                    updated += 1

                    logger.info(
                        f"[价格更新] {product.title}: "
                        f"¥{old_price} -> ¥{new_price}"
                    )
            except Exception as e:
                logger.error(f"[价格更新失败] {product.id}: {e}")

        await db.commit()
        logger.info(f"[价格更新] 完成，共更新 {updated}/{len(products)} 个商品")
        return updated

    async def check_alerts(self, db: AsyncSession) -> list:
        """
        检查所有价格提醒
        返回需要通知的提醒列表
        """
        # 查询所有未触发的活跃提醒
        result = await db.execute(
            select(PriceAlert).where(
                PriceAlert.is_active == True,
                PriceAlert.triggered == False,
            )
        )
        alerts = result.scalars().all()
        triggered = []

        for alert in alerts:
            # 获取对应商品
            product_result = await db.execute(
                select(Product).where(Product.id == alert.product_id)
            )
            product = product_result.scalar_one_or_none()
            if not product:
                continue

            # 检查是否达到目标价格
            if product.price <= alert.target_price:
                alert.triggered = True
                alert.triggered_at = datetime.utcnow()
                triggered.append({
                    "alert": alert,
                    "product": product,
                    "current_price": product.price,
                    "target_price": alert.target_price,
                })
                logger.info(
                    f"[价格提醒触发] {product.title}: "
                    f"当前¥{product.price} <= 目标¥{alert.target_price}"
                )

        await db.commit()
        return triggered

    async def get_price_history(self, product_id: int, db: AsyncSession, days: int = 30) -> list:
        """获取商品价格历史"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.product_id == product_id,
                PriceHistory.recorded_at >= cutoff,
            )
            .order_by(PriceHistory.recorded_at.asc())
        )
        records = result.scalars().all()
        return [
            {
                "price": r.price,
                "platform": r.platform,
                "time": r.recorded_at.isoformat() if r.recorded_at else None,
            }
            for r in records
        ]
