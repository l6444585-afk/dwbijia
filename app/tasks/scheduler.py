"""
定时任务调度器

- 每小时更新商品价格
- 每30分钟检查价格提醒
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from app.models.database import async_session
from app.services.monitor import MonitorService
from app.services.notification import NotificationService

scheduler = AsyncIOScheduler()
monitor_svc = MonitorService()
notify_svc = NotificationService()


async def job_update_prices():
    """定时更新所有商品价格"""
    logger.info("[定时任务] 开始更新商品价格...")
    async with async_session() as db:
        try:
            updated = await monitor_svc.update_all_prices(db)
            logger.info(f"[定时任务] 价格更新完成，更新了 {updated} 个商品")
        except Exception as e:
            logger.error(f"[定时任务] 价格更新失败: {e}")


async def job_check_alerts():
    """定时检查价格提醒"""
    logger.info("[定时任务] 检查价格提醒...")
    async with async_session() as db:
        try:
            triggered = await monitor_svc.check_alerts(db)
            for alert_data in triggered:
                await notify_svc.send_price_alert(alert_data)
            if triggered:
                logger.info(f"[定时任务] 触发了 {len(triggered)} 个价格提醒")
        except Exception as e:
            logger.error(f"[定时任务] 价格提醒检查失败: {e}")


def start_scheduler():
    """启动定时任务"""
    # 每小时更新价格
    scheduler.add_job(job_update_prices, "interval", hours=1, id="update_prices")
    # 每30分钟检查提醒
    scheduler.add_job(job_check_alerts, "interval", minutes=30, id="check_alerts")

    scheduler.start()
    logger.info("[定时任务] 调度器已启动")


def stop_scheduler():
    """停止定时任务"""
    scheduler.shutdown()
    logger.info("[定时任务] 调度器已停止")
