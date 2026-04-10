"""
数据访问层 - Product Repository

提供商品数据的CRUD操作
"""
from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from datetime import datetime, timedelta

from app.models.product import Product, PriceHistory
from loguru import logger


class ProductRepository:
    """商品数据访问层"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, product_data: Dict[str, Any]) -> Product:
        """创建商品"""
        product = Product(**product_data)
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(product)
        
        logger.debug(f"创建商品: {product.id} - {product.title}")
        return product
    
    async def get_by_id(self, product_id: int) -> Optional[Product]:
        """根据ID获取商品"""
        result = await self.session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_platform_id(self, platform: str, platform_id: str) -> Optional[Product]:
        """根据平台ID获取商品"""
        result = await self.session.execute(
            select(Product).where(
                and_(
                    Product.platform == platform,
                    Product.platform_id == platform_id
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def get_by_article(self, article_no: str) -> Optional[Product]:
        """根据货号获取商品"""
        result = await self.session.execute(
            select(Product).where(Product.article_no == article_no)
        )
        return result.scalar_one_or_none()
    
    async def update(self, product_id: int, update_data: Dict[str, Any]) -> Optional[Product]:
        """更新商品"""
        product = await self.get_by_id(product_id)
        if not product:
            return None
        
        for key, value in update_data.items():
            if hasattr(product, key):
                setattr(product, key, value)
        
        product.updated_at = datetime.now()
        await self.session.flush()
        await self.session.refresh(product)
        
        logger.debug(f"更新商品: {product.id}")
        return product
    
    async def delete(self, product_id: int) -> bool:
        """删除商品"""
        product = await self.get_by_id(product_id)
        if not product:
            return False
        
        await self.session.delete(product)
        await self.session.flush()
        
        logger.debug(f"删除商品: {product_id}")
        return True
    
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Product]:
        """获取所有商品"""
        result = await self.session.execute(
            select(Product)
            .order_by(Product.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()
    
    async def list_by_platform(self, platform: str, skip: int = 0, limit: int = 100) -> List[Product]:
        """根据平台获取商品"""
        result = await self.session.execute(
            select(Product)
            .where(Product.platform == platform)
            .order_by(Product.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()
    
    async def list_profitable(self, min_profit: float = 0, skip: int = 0, limit: int = 100) -> List[Product]:
        """获取有利润的商品"""
        result = await self.session.execute(
            select(Product)
            .where(Product.profit > min_profit)
            .order_by(Product.profit.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()
    
    async def search(self, keyword: str, skip: int = 0, limit: int = 100) -> List[Product]:
        """搜索商品"""
        result = await self.session.execute(
            select(Product)
            .where(
                or_(
                    Product.title.contains(keyword),
                    Product.article_no.contains(keyword),
                    Product.model.contains(keyword),
                    Product.brand.contains(keyword),
                )
            )
            .order_by(Product.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()
    
    async def count_all(self) -> int:
        """统计商品总数"""
        result = await self.session.execute(
            select(func.count(Product.id))
        )
        return result.scalar()
    
    async def count_by_platform(self, platform: str) -> int:
        """统计平台商品数"""
        result = await self.session.execute(
            select(func.count(Product.id))
            .where(Product.platform == platform)
        )
        return result.scalar()
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = await self.count_all()
        
        profitable_result = await self.session.execute(
            select(func.count(Product.id))
            .where(Product.profit > 0)
        )
        profitable = profitable_result.scalar()
        
        loss_result = await self.session.execute(
            select(func.count(Product.id))
            .where(Product.profit < 0)
        )
        loss = loss_result.scalar()
        
        avg_profit_result = await self.session.execute(
            select(func.avg(Product.profit))
            .where(Product.profit.isnot(None))
        )
        avg_profit = avg_profit_result.scalar() or 0
        
        return {
            "total": total,
            "profitable": profitable,
            "loss": loss,
            "avg_profit": round(avg_profit, 2),
        }
    
    async def batch_create(self, products_data: List[Dict[str, Any]]) -> List[Product]:
        """批量创建商品"""
        products = [Product(**data) for data in products_data]
        self.session.add_all(products)
        await self.session.flush()
        
        for product in products:
            await self.session.refresh(product)
        
        logger.debug(f"批量创建商品: {len(products)} 条")
        return products
    
    async def batch_update_prices(self, updates: List[Dict[str, Any]]) -> int:
        """批量更新价格"""
        count = 0
        for update in updates:
            product_id = update.pop('id')
            product = await self.update(product_id, update)
            if product:
                count += 1
        
        logger.debug(f"批量更新价格: {count} 条")
        return count


class PriceHistoryRepository:
    """价格历史数据访问层"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, history_data: Dict[str, Any]) -> PriceHistory:
        """创建价格历史"""
        history = PriceHistory(**history_data)
        self.session.add(history)
        await self.session.flush()
        await self.session.refresh(history)
        
        return history
    
    async def get_by_product(self, product_id: int, days: int = 30) -> List[PriceHistory]:
        """获取商品价格历史"""
        start_date = datetime.now() - timedelta(days=days)
        
        result = await self.session.execute(
            select(PriceHistory)
            .where(
                and_(
                    PriceHistory.product_id == product_id,
                    PriceHistory.recorded_at >= start_date
                )
            )
            .order_by(PriceHistory.recorded_at.desc())
        )
        return result.scalars().all()
    
    async def get_latest(self, product_id: int) -> Optional[PriceHistory]:
        """获取最新价格"""
        result = await self.session.execute(
            select(PriceHistory)
            .where(PriceHistory.product_id == product_id)
            .order_by(PriceHistory.recorded_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
