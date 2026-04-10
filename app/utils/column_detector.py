"""
列自动识别模块 - 从price_compare迁移

功能:
1. 自动识别Excel列名
2. 智能匹配列角色
3. 支持多种列名格式
"""
from typing import Dict, List, Optional
import re
from loguru import logger


class ColumnDetector:
    """列自动识别器"""
    
    COL_RULES = {
        "taobao_id": [
            "商品id", "itemid", "宝贝id", "数字id", "id", "商品id",
            "商品编号", "编号", "数字ID"
        ],
        "price": [
            "普惠到手价", "到手价", "最终价", "售价", "价格",
            "成交价", "优惠价", "活动价到手", "到手价格"
        ],
        "model": [
            "model", "款式", "型号", "系列", "model number",
            "型号编码", "款式编号"
        ],
        "title": [
            "标题", "title", "商品名", "产品名", "名称",
            "商品名称", "产品名称", "宝贝标题"
        ],
        "article": [
            "货号", "article no", "sku", "款号", "article",
            "商品货号", "款式货号", "sku编号"
        ],
        "tag_price": [
            "吊牌价", "原价", "tag price", "标价",
            "建议零售价", "零售价"
        ],
        "act_price": [
            "活动价", "促销价", "优惠价", "折扣价",
            "活动价格", "促销价格"
        ],
        "stock": [
            "库存", "stock", "id库存", "商品库存",
            "库存数量", "可售数量"
        ],
        "store_coupon": [
            "店铺券", "店铺优惠券", "商家券",
            "店铺优惠", "商家优惠"
        ],
        "official_discount": [
            "官方立减", "立减", "官方优惠", "平台立减",
            "满减", "优惠立减"
        ],
        "cps_coupon": [
            "cps券", "cps coupon", "cps优惠",
            "cps优惠券", "推广券"
        ],
        "status": [
            "商品状态", "状态", "上架状态",
            "销售状态", "商品状态"
        ],
    }
    
    def __init__(self):
        self.detected_columns: Dict[str, str] = {}
        self.unmatched_columns: List[str] = []
    
    def detect(self, columns: List[str]) -> Dict[str, str]:
        """
        自动识别列名
        
        Args:
            columns: Excel列名列表
            
        Returns:
            识别结果字典 {角色: 列名}
        """
        self.detected_columns = {}
        self.unmatched_columns = []
        
        columns_lower = [col.lower().strip() for col in columns]
        
        for role, patterns in self.COL_RULES.items():
            matched = False
            
            for i, col_lower in enumerate(columns_lower):
                original_col = columns[i]
                
                for pattern in patterns:
                    if pattern.lower() in col_lower or col_lower in pattern.lower():
                        self.detected_columns[role] = original_col
                        matched = True
                        logger.debug(f"识别列: {original_col} -> {role}")
                        break
                
                if matched:
                    break
        
        for col in columns:
            if col not in self.detected_columns.values():
                self.unmatched_columns.append(col)
        
        logger.info(f"列识别完成: {len(self.detected_columns)}/{len(columns)} 列已识别")
        
        return self.detected_columns
    
    def get_column(self, role: str) -> Optional[str]:
        """获取指定角色的列名"""
        return self.detected_columns.get(role)
    
    def get_detection_report(self) -> str:
        """生成识别报告"""
        report = []
        report.append("="*60)
        report.append("列识别报告")
        report.append("="*60)
        
        report.append("\n已识别的列:")
        for role, col in self.detected_columns.items():
            report.append(f"  ✓ {role}: {col}")
        
        if self.unmatched_columns:
            report.append("\n未识别的列:")
            for col in self.unmatched_columns:
                report.append(f"  ✗ {col}")
        
        report.append("="*60)
        
        return "\n".join(report)


def detect_columns(columns: List[str]) -> Dict[str, str]:
    """
    便捷函数: 自动识别列名
    
    Args:
        columns: Excel列名列表
        
    Returns:
        识别结果字典 {角色: 列名}
    """
    detector = ColumnDetector()
    return detector.detect(columns)


if __name__ == "__main__":
    test_columns = [
        "商品ID", "到手价", "货号", "标题", "吊牌价",
        "活动价", "库存", "商品状态", "其他列"
    ]
    
    detector = ColumnDetector()
    result = detector.detect(test_columns)
    
    print(detector.get_detection_report())
