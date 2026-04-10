"""
爬虫系统管理 API

- 系统状态监控
- 手动触发爬取
- 代理池管理
- 数据质量报告
"""
from fastapi import APIRouter, Query
from app.scrapers.sdk.client import scraper_client
from app.scrapers.platforms.base import _proxy_pool, _anti_detect

router = APIRouter(prefix="/api/scraper", tags=["爬虫管理"])


@router.get("/status")
async def system_status():
    """获取爬虫系统完整状态"""
    return scraper_client.get_system_status()


@router.get("/health")
async def health_status(platform: str = ""):
    """获取平台健康状态"""
    return scraper_client.health.get_status(platform)


@router.get("/quality")
async def quality_stats():
    """获取数据质量统计"""
    return scraper_client.quality.get_stats()


@router.get("/anti-detect/stats")
async def anti_detect_stats(platform: str = ""):
    """获取反爬策略效果统计"""
    return _anti_detect.get_strategy_stats(platform)


@router.get("/proxy/stats")
async def proxy_stats():
    """获取代理池状态"""
    return _proxy_pool.get_stats()


@router.post("/proxy/add")
async def add_proxy(url: str, source: str = "manual"):
    """手动添加代理"""
    _proxy_pool.add_proxy(url, source)
    return {"message": f"已添加代理: {url}", "pool_size": _proxy_pool.size}


@router.post("/proxy/health-check")
async def run_proxy_health_check():
    """手动触发代理健康检查"""
    await _proxy_pool.health_check()
    return _proxy_pool.get_stats()


@router.post("/search")
async def manual_search(
    keyword: str = Query(..., min_length=1),
    page: int = 1,
    page_size: int = 20,
):
    """手动触发搜索（用于测试）"""
    result = await scraper_client.search(keyword, page, page_size)
    return result


@router.get("/alerts")
async def get_alerts(limit: int = 50):
    """获取系统告警"""
    return {"alerts": scraper_client.health.get_alerts(limit)}
