"""商品搜索与比价API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.product import Product
from app.services.compare import CompareService
from app.services.recommend import RecommendService
from app.utils.cache import cache

router = APIRouter(prefix="/api/products", tags=["商品"])
compare_svc = CompareService()
recommend_svc = RecommendService()


@router.get("/search")
async def search_products(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    """搜索并比价"""
    # 查缓存
    cache_key = f"search:{keyword}:{page}:{page_size}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # 搜索并比价
    result = await compare_svc.search_and_compare(keyword, page, page_size)

    # 添加推荐
    result["recommendation"] = recommend_svc.get_platform_recommendation(result)
    result["best_deals"] = recommend_svc.get_best_deals(result, top_n=5)

    # 缓存5分钟
    await cache.set(cache_key, result, ttl=300)
    return result


@router.get("/detail/{platform}/{product_id}")
async def get_product_detail(platform: str, product_id: str):
    """获取商品详情"""
    cache_key = f"detail:{platform}:{product_id}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    if platform == "taobao":
        detail = await compare_svc.taobao.get_detail(product_id)
    elif platform == "dewu":
        detail = await compare_svc.dewu.get_detail(product_id)
    else:
        return {"error": "不支持的平台"}

    if detail:
        await cache.set(cache_key, detail, ttl=600)
    return detail or {"error": "商品未找到"}


@router.get("/history")
async def search_history(
    keyword: str = Query("", description="搜索关键词"),
    platform: str = Query("", description="平台筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """搜索数据库中已保存的商品"""
    query = select(Product)
    if keyword:
        query = query.where(Product.title.contains(keyword))
    if platform:
        query = query.where(Product.platform == platform)

    query = query.order_by(Product.updated_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    products = result.scalars().all()

    return {
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "platform": p.platform,
                "platform_id": p.platform_id,
                "price": p.price,
                "original_price": p.original_price,
                "image_url": p.image_url,
                "sales": p.sales,
                "rating": p.rating,
                "shop_name": p.shop_name,
                "brand": p.brand,
                "url": p.url,
            }
            for p in products
        ],
        "page": page,
        "page_size": page_size,
    }
