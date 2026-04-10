"""
跨平台智能比价系统 - 主入口

启动方式:
    python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

或直接:
    python app/main.py
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

from config.settings import settings
from app.models.database import init_db
from app.api import products, prices, users
from app.api import scraper_api
from app.api import compare
from app.tasks.scheduler import start_scheduler, stop_scheduler
from app.scrapers.sdk.client import scraper_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动
    logger.info(f"🚀 {settings.APP_NAME} 启动中...")
    await init_db()
    logger.info("数据库初始化完成")
    await scraper_client.initialize()
    logger.info("爬虫客户端初始化完成")
    start_scheduler()
    yield
    # 关闭
    stop_scheduler()
    await scraper_client.shutdown()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="淘宝-得物跨平台智能比价系统",
    version="1.0.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(products.router)
app.include_router(prices.router)
app.include_router(users.router)
app.include_router(scraper_api.router)
app.include_router(compare.router)

# 静态文件
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# 首页
@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


# 健康检查
@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
