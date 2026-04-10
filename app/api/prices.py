"""价格趋势与监控API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.product import Product, PriceHistory
from app.models.user import PriceAlert
from app.services.monitor import MonitorService
from app.utils.auth import require_user
from app.utils.cache import cache

router = APIRouter(prefix="/api/prices", tags=["价格"])
monitor_svc = MonitorService()


@router.get("/trend/{product_id}")
async def get_price_trend(
    product_id: int,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """获取商品价格走势"""
    cache_key = f"trend:{product_id}:{days}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # 获取商品信息
    product_result = await db.execute(select(Product).where(Product.id == product_id))
    product = product_result.scalar_one_or_none()
    if not product:
        return {"error": "商品不存在"}

    # 获取价格历史
    history = await monitor_svc.get_price_history(product_id, db, days)

    result = {
        "product": {
            "id": product.id,
            "title": product.title,
            "platform": product.platform,
            "current_price": product.price,
        },
        "history": history,
        "stats": _calc_trend_stats(history, product.price),
    }

    await cache.set(cache_key, result, ttl=600)
    return result


@router.post("/alert")
async def create_alert(
    product_id: int,
    target_price: float,
    notify_email: bool = True,
    notify_sms: bool = False,
    notify_push: bool = False,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """创建价格监控提醒"""
    # 检查商品是否存在
    product_result = await db.execute(select(Product).where(Product.id == product_id))
    product = product_result.scalar_one_or_none()
    if not product:
        return {"error": "商品不存在"}

    alert = PriceAlert(
        user_id=user.id,
        product_id=product_id,
        target_price=target_price,
        notify_email=notify_email,
        notify_sms=notify_sms,
        notify_push=notify_push,
    )
    db.add(alert)
    await db.commit()

    return {
        "message": "价格提醒已创建",
        "alert_id": alert.id,
        "product": product.title,
        "current_price": product.price,
        "target_price": target_price,
    }


@router.get("/alerts")
async def list_alerts(
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """查看我的价格提醒"""
    result = await db.execute(
        select(PriceAlert).where(PriceAlert.user_id == user.id).order_by(PriceAlert.created_at.desc())
    )
    alerts = result.scalars().all()

    items = []
    for a in alerts:
        p_result = await db.execute(select(Product).where(Product.id == a.product_id))
        p = p_result.scalar_one_or_none()
        items.append({
            "id": a.id,
            "product_id": a.product_id,
            "product_title": p.title if p else "未知",
            "current_price": p.price if p else 0,
            "target_price": a.target_price,
            "is_active": a.is_active,
            "triggered": a.triggered,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })

    return {"alerts": items}


@router.delete("/alert/{alert_id}")
async def delete_alert(
    alert_id: int,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """删除价格提醒"""
    result = await db.execute(
        select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user.id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return {"error": "提醒不存在"}

    await db.delete(alert)
    await db.commit()
    return {"message": "已删除"}


def _calc_trend_stats(history: list, current_price: float) -> dict:
    """计算价格趋势统计"""
    if not history:
        return {"min": current_price, "max": current_price, "avg": current_price, "trend": "stable"}

    prices = [h["price"] for h in history]
    min_p = min(prices)
    max_p = max(prices)
    avg_p = sum(prices) / len(prices)

    # 简单趋势判断
    if len(prices) >= 2:
        recent = prices[-3:] if len(prices) >= 3 else prices
        earlier = prices[:3]
        if sum(recent) / len(recent) < sum(earlier) / len(earlier):
            trend = "down"
        elif sum(recent) / len(recent) > sum(earlier) / len(earlier):
            trend = "up"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "min": round(min_p, 2),
        "max": round(max_p, 2),
        "avg": round(avg_p, 2),
        "trend": trend,
        "is_lowest": current_price <= min_p,
    }
