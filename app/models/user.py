from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from app.models.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    phone = Column(String(20), comment="手机号，用于短信通知")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Favorite(Base):
    """用户收藏表"""
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class PriceAlert(Base):
    """价格监控提醒表"""
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    target_price = Column(Float, nullable=False, comment="目标价格")
    notify_email = Column(Boolean, default=True)
    notify_sms = Column(Boolean, default=False)
    notify_push = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    triggered = Column(Boolean, default=False, comment="是否已触发")
    triggered_at = Column(DateTime, comment="触发时间")
    created_at = Column(DateTime, server_default=func.now())
