"""用户系统API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.user import User, Favorite
from app.models.product import Product
from app.utils.auth import hash_password, verify_password, create_token, require_user

router = APIRouter(prefix="/api/users", tags=["用户"])


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    phone: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    # 检查用户名和邮箱
    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "用户名或邮箱已存在")

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        phone=req.phone,
    )
    db.add(user)
    await db.commit()

    token = create_token(user.id, user.username)
    return {"message": "注册成功", "token": token, "user": {"id": user.id, "username": user.username}}


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "用户名或密码错误")

    token = create_token(user.id, user.username)
    return {"token": token, "user": {"id": user.id, "username": user.username, "email": user.email}}


@router.get("/me")
async def get_me(user=Depends(require_user)):
    """获取当前用户信息"""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
    }


@router.post("/favorites/{product_id}")
async def add_favorite(
    product_id: int,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """收藏商品"""
    # 检查是否已收藏
    existing = await db.execute(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.product_id == product_id)
    )
    if existing.scalar_one_or_none():
        return {"message": "已收藏"}

    fav = Favorite(user_id=user.id, product_id=product_id)
    db.add(fav)
    await db.commit()
    return {"message": "收藏成功"}


@router.delete("/favorites/{product_id}")
async def remove_favorite(
    product_id: int,
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """取消收藏"""
    result = await db.execute(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.product_id == product_id)
    )
    fav = result.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
    return {"message": "已取消收藏"}


@router.get("/favorites")
async def list_favorites(
    user=Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """我的收藏列表"""
    result = await db.execute(
        select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())
    )
    favs = result.scalars().all()

    items = []
    for f in favs:
        p_result = await db.execute(select(Product).where(Product.id == f.product_id))
        p = p_result.scalar_one_or_none()
        if p:
            items.append({
                "id": p.id,
                "title": p.title,
                "platform": p.platform,
                "price": p.price,
                "image_url": p.image_url,
                "url": p.url,
                "favorited_at": f.created_at.isoformat() if f.created_at else None,
            })

    return {"favorites": items}
