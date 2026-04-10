from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, Index
from sqlalchemy.sql import func
from app.models.database import Base


class Product(Base):
    """商品信息表"""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, comment="商品标题")
    platform = Column(String(20), nullable=False, comment="平台: taobao/dewu")
    platform_id = Column(String(100), nullable=False, comment="平台商品ID")
    url = Column(String(1000), comment="商品链接")
    image_url = Column(String(1000), comment="商品主图")
    price = Column(Float, nullable=False, comment="当前价格")
    original_price = Column(Float, comment="原价")
    sales = Column(Integer, default=0, comment="销量")
    rating = Column(Float, default=0, comment="评分")
    shop_name = Column(String(200), comment="店铺名称")
    category = Column(String(100), comment="分类")
    brand = Column(String(100), comment="品牌")
    specs = Column(JSON, comment="规格参数")
    extra_data = Column(JSON, comment="其他平台特有数据")
    
    taobao_listed = Column(Float, comment="淘宝到手价（Excel原始值）")
    activity_deduct = Column(Float, default=0, comment="活动立减")
    coupon_share = Column(Float, default=0, comment="消费券分摊额")
    jingou_deduct = Column(Float, default=0, comment="购物金抵扣额")
    taobao_final = Column(Float, comment="淘宝最终成本")
    dewu_price = Column(Float, comment="得物个人卖家价格")
    dewu_net = Column(Float, comment="得物扣佣后收入")
    profit = Column(Float, comment="差价利润")
    buyers_count = Column(Integer, comment="得物最近付款人数")
    is_manual = Column(Integer, default=0, comment="是否手动录入（0否1是）")
    article_no = Column(String(100), comment="货号")
    model = Column(String(100), comment="型号")
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_platform_pid", "platform", "platform_id", unique=True),
        Index("idx_title", "title"),
        Index("idx_category", "category"),
        Index("idx_article", "article_no"),
        Index("idx_profit", "profit"),
    )


class PriceHistory(Base):
    """价格历史记录表"""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, comment="商品ID")
    platform = Column(String(20), nullable=False)
    price = Column(Float, nullable=False, comment="价格")
    recorded_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_product_time", "product_id", "recorded_at"),
    )
