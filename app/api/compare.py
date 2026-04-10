"""
price_compare API端点

提供Excel上传、价格计算、得物爬取、手动录入、数据导出等功能
"""
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import pandas as pd
import uuid
import io
import asyncio
import json

from app.models.database import get_db
from app.repositories.product_repository import ProductRepository
from app.utils.column_detector import ColumnDetector
from app.services.price_calculator import PriceCalculator, create_calculator
from loguru import logger


router = APIRouter(prefix="/api/compare", tags=["价格对比"])


class CalculateRequest(BaseModel):
    """计算请求"""
    file_id: str = Field(..., description="文件ID")
    ext: str = Field(..., description="文件扩展名")
    coupon: Optional[str] = Field(None, description="消费券，如 2000-200")
    commission: float = Field(0.08, description="得物佣金率")
    jingou_charge: float = Field(2000, description="购物金充值金额")
    jingou_credit: float = Field(2100, description="购物金到账金额")
    activity_deduct: float = Field(0, description="活动立减")


class ManualPriceRequest(BaseModel):
    """手动录入价格请求"""
    product_id: int = Field(..., description="商品ID")
    dewu_price: float = Field(..., gt=0, description="得物价格")
    buyers_count: Optional[int] = Field(None, description="付款人数")


class ExportRequest(BaseModel):
    """导出请求"""
    rows: List[Dict[str, Any]] = Field(..., description="要导出的数据行")


uploaded_files: Dict[str, Dict[str, Any]] = {}


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    上传Excel文件并解析
    
    Args:
        file: Excel文件
        
    Returns:
        文件ID、列识别结果、解析后的数据
    """
    try:
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="只支持.xlsx和.xls格式文件")
        
        content = await file.read()
        
        df = pd.read_excel(io.BytesIO(content))
        
        df = df.fillna('')
        
        file_id = str(uuid.uuid4())
        ext = '.xlsx' if file.filename.endswith('.xlsx') else '.xls'
        
        detector = ColumnDetector()
        detected = detector.detect(df.columns.tolist())
        
        rows = []
        for idx, row in df.iterrows():
            row_data = {"_idx": idx}
            
            for col in df.columns:
                row_data[f"col_{col}"] = row[col]
            
            search_term = ""
            search_src = ""
            
            if detected.get("article"):
                article = str(row.get(detected["article"], ""))
                if article and article != 'nan':
                    search_term = article
                    search_src = "货号"
            
            if not search_term and detected.get("model"):
                model = str(row.get(detected["model"], ""))
                if model and model != 'nan':
                    search_term = model
                    search_src = "MODEL"
            
            if not search_term and detected.get("title"):
                title = str(row.get(detected["title"], ""))
                if title and title != 'nan':
                    import re
                    matches = re.findall(r'[A-Z]{2,}\d+[A-Z0-9]*', title)
                    if matches:
                        search_term = matches[0]
                        search_src = "标题"
            
            row_data["_search_term"] = search_term
            row_data["_search_src"] = search_src
            
            rows.append(row_data)
        
        uploaded_files[file_id] = {
            "df": df,
            "ext": ext,
            "detected": detected,
            "rows": rows,
        }
        
        logger.info(f"上传文件成功: {file.filename}, {len(rows)}行")
        
        return {
            "file_id": file_id,
            "ext": ext,
            "columns": df.columns.tolist(),
            "detected": detected,
            "total": len(rows),
            "rows": rows,
        }
        
    except Exception as e:
        logger.error(f"上传文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calculate")
async def calculate_prices(
    request: CalculateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    计算淘宝最低到手价
    
    Args:
        request: 计算请求参数
        
    Returns:
        计算结果
    """
    try:
        file_data = uploaded_files.get(request.file_id)
        if not file_data:
            raise HTTPException(status_code=404, detail="文件未找到，请重新上传")
        
        df = file_data["df"]
        detected = file_data["detected"]
        rows = file_data["rows"]
        
        calculator = create_calculator(
            coupon_str=request.coupon,
            jingou_charge=request.jingou_charge,
            jingou_credit=request.jingou_credit,
            commission_rate=request.commission,
            activity_deduct=request.activity_deduct,
        )
        
        price_col = detected.get("price")
        if not price_col:
            raise HTTPException(status_code=400, detail="未识别到手价列")
        
        total_price = sum(
            float(row.get(f"col_{price_col}", 0) or 0)
            for row in rows
        )
        
        results = []
        for row in rows:
            taobao_listed = float(row.get(f"col_{price_col}", 0) or 0)
            
            article_no = ""
            if detected.get("article"):
                article_no = str(row.get(f"col_{detected['article']}", ""))
            
            result = calculator.calculate_single(
                article_no=article_no,
                taobao_listed=taobao_listed,
                total_price=total_price,
            )
            
            result_dict = {
                "_idx": row["_idx"],
                "taobao_listed": result.taobao_listed,
                "activity_deduct": result.activity_deduct,
                "coupon_share": result.coupon_share,
                "jingou_deduct": result.jingou_deduct,
                "taobao_final": result.taobao_final,
            }
            
            results.append(result_dict)
        
        logger.info(f"计算价格完成: {len(results)}条")
        
        return {
            "rows": results,
            "total": len(results),
            "coupon": f"满{calculator.coupon.threshold}减{calculator.coupon.discount}" if calculator.coupon else None,
            "jingou_rate": round(calculator.jingou.discount_rate * 100, 2),
            "commission": request.commission * 100,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"计算价格失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual_price")
async def update_manual_price(
    request: ManualPriceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    手动录入得物价格
    
    Args:
        request: 手动录入请求
        
    Returns:
        更新后的商品信息
    """
    try:
        repo = ProductRepository(db)
        
        product = await repo.update(request.product_id, {
            "dewu_price": request.dewu_price,
            "buyers_count": request.buyers_count,
            "is_manual": 1,
        })
        
        if not product:
            raise HTTPException(status_code=404, detail="商品未找到")
        
        if product.taobao_final:
            commission_rate = 0.08
            dewu_net = round(request.dewu_price * (1 - commission_rate), 2)
            profit = round(dewu_net - product.taobao_final, 2)
            
            product = await repo.update(request.product_id, {
                "dewu_net": dewu_net,
                "profit": profit,
            })
        
        logger.info(f"手动录入价格: 商品{request.product_id}, 价格{request.dewu_price}")
        
        return {
            "success": True,
            "product": {
                "id": product.id,
                "dewu_price": product.dewu_price,
                "dewu_net": product.dewu_net,
                "profit": product.profit,
                "is_manual": product.is_manual,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手动录入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
async def export_excel(
    request: ExportRequest,
):
    """
    导出Excel结果
    
    Args:
        request: 导出请求
        
    Returns:
        Excel文件流
    """
    try:
        if not request.rows:
            raise HTTPException(status_code=400, detail="没有数据可导出")
        
        df = pd.DataFrame(request.rows)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='比价结果')
        
        output.seek(0)
        
        filename = f"比价结果_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        
        logger.info(f"导出Excel: {filename}, {len(request.rows)}条")
        
        return StreamingResponse(
            io.BytesIO(output.read()),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics(
    db: AsyncSession = Depends(get_db),
):
    """
    获取统计信息
    
    Returns:
        统计数据
    """
    try:
        repo = ProductRepository(db)
        stats = await repo.get_statistics()
        
        return {
            "success": True,
            "statistics": stats,
        }
        
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    platform: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    获取商品列表
    
    Args:
        skip: 跳过数量
        limit: 返回数量
        platform: 平台筛选
        keyword: 关键词搜索
        
    Returns:
        商品列表
    """
    try:
        repo = ProductRepository(db)
        
        if keyword:
            products = await repo.search(keyword, skip, limit)
        elif platform:
            products = await repo.list_by_platform(platform, skip, limit)
        else:
            products = await repo.list_all(skip, limit)
        
        return {
            "success": True,
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "platform": p.platform,
                    "price": p.price,
                    "taobao_final": p.taobao_final,
                    "dewu_price": p.dewu_price,
                    "profit": p.profit,
                    "article_no": p.article_no,
                    "is_manual": p.is_manual,
                }
                for p in products
            ],
            "skip": skip,
            "limit": limit,
        }
        
    except Exception as e:
        logger.error(f"获取列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
