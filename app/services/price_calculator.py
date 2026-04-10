"""
价格计算服务 - 从price_compare迁移

功能:
1. 计算淘宝最低到手价
2. 解析消费券配置
3. 计算购物金折扣
4. 计算得物扣佣后收入
5. 计算差价利润
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from loguru import logger
import re


@dataclass
class CouponConfig:
    """消费券配置"""
    threshold: float  # 门槛
    discount: float   # 优惠金额
    
    @classmethod
    def parse(cls, coupon_str: str) -> Optional['CouponConfig']:
        """
        解析消费券字符串
        
        支持格式:
        - "2000-200" 表示满2000减200
        - "2000减200"
        - "满2000减200"
        """
        if not coupon_str:
            return None
        
        coupon_str = coupon_str.strip()
        
        match = re.match(r'(?:满)?(\d+(?:\.\d+)?)[减-](\d+(?:\.\d+)?)', coupon_str)
        if match:
            threshold = float(match.group(1))
            discount = float(match.group(2))
            return cls(threshold=threshold, discount=discount)
        
        return None
    
    def calculate_share(self, price: float, total_price: float) -> float:
        """
        计算消费券分摊额
        
        Args:
            price: 单个商品价格
            total_price: 总价格
            
        Returns:
            分摊的优惠金额
        """
        if total_price < self.threshold:
            return 0
        
        share_ratio = price / total_price
        return round(self.discount * share_ratio, 2)


@dataclass
class JingouConfig:
    """购物金配置"""
    charge: float    # 充值金额
    credit: float    # 到账金额
    
    @property
    def discount_rate(self) -> float:
        """计算折扣率"""
        if self.credit <= 0:
            return 0
        return round((self.credit - self.charge) / self.credit, 4)
    
    def calculate_deduct(self, price: float) -> float:
        """
        计算购物金抵扣额
        
        Args:
            price: 商品价格
            
        Returns:
            抵扣金额
        """
        return round(price * self.discount_rate, 2)


@dataclass
class PriceResult:
    """价格计算结果"""
    article_no: str          # 货号
    taobao_listed: float     # 淘宝到手价（Excel原始值）
    activity_deduct: float   # 活动立减
    coupon_share: float      # 消费券分摊额
    jingou_deduct: float     # 购物金抵扣额
    taobao_final: float      # 淘宝最终成本
    dewu_price: Optional[float] = None      # 得物个人卖家价格
    dewu_net: Optional[float] = None         # 得物扣佣后收入
    profit: Optional[float] = None           # 净利润
    commission_rate: float = 0.08            # 得物佣金率
    buyers_count: Optional[int] = None       # 付款人数


class PriceCalculator:
    """价格计算器"""
    
    def __init__(
        self,
        coupon: Optional[CouponConfig] = None,
        jingou: Optional[JingouConfig] = None,
        commission_rate: float = 0.08,
        activity_deduct: float = 0,
    ):
        self.coupon = coupon
        self.jingou = jingou or JingouConfig(charge=2000, credit=2100)
        self.commission_rate = commission_rate
        self.activity_deduct = activity_deduct
    
    def calculate_single(
        self,
        article_no: str,
        taobao_listed: float,
        total_price: float = None,
        dewu_price: float = None,
        buyers_count: int = None,
    ) -> PriceResult:
        """
        计算单个商品价格
        
        Args:
            article_no: 货号
            taobao_listed: 淘宝到手价
            total_price: 总价格（用于消费券分摊）
            dewu_price: 得物价格
            buyers_count: 付款人数
            
        Returns:
            价格计算结果
        """
        if total_price is None:
            total_price = taobao_listed
        
        activity_deduct = self.activity_deduct
        
        coupon_share = 0
        if self.coupon and total_price >= self.coupon.threshold:
            coupon_share = self.coupon.calculate_share(taobao_listed, total_price)
        
        jingou_deduct = self.jingou.calculate_deduct(taobao_listed)
        
        taobao_final = taobao_listed - activity_deduct - coupon_share - jingou_deduct
        taobao_final = round(taobao_final, 2)
        
        dewu_net = None
        profit = None
        if dewu_price is not None and dewu_price > 0:
            dewu_net = round(dewu_price * (1 - self.commission_rate), 2)
            profit = round(dewu_net - taobao_final, 2)
        
        result = PriceResult(
            article_no=article_no,
            taobao_listed=taobao_listed,
            activity_deduct=activity_deduct,
            coupon_share=coupon_share,
            jingou_deduct=jingou_deduct,
            taobao_final=taobao_final,
            dewu_price=dewu_price,
            dewu_net=dewu_net,
            profit=profit,
            commission_rate=self.commission_rate,
            buyers_count=buyers_count,
        )
        
        logger.debug(f"计算价格: {article_no} - 淘宝最终 {taobao_final}, 得物 {dewu_price}, 利润 {profit}")
        
        return result
    
    def calculate_batch(
        self,
        items: List[Dict[str, Any]],
    ) -> List[PriceResult]:
        """
        批量计算价格
        
        Args:
            items: 商品列表，每个商品包含:
                - article_no: 货号
                - taobao_listed: 淘宝到手价
                - dewu_price: 得物价格（可选）
                - buyers_count: 付款人数（可选）
                
        Returns:
            价格计算结果列表
        """
        total_price = sum(item.get('taobao_listed', 0) for item in items)
        
        results = []
        for item in items:
            result = self.calculate_single(
                article_no=item.get('article_no', ''),
                taobao_listed=item.get('taobao_listed', 0),
                total_price=total_price,
                dewu_price=item.get('dewu_price'),
                buyers_count=item.get('buyers_count'),
            )
            results.append(result)
        
        logger.info(f"批量计算价格: {len(results)} 条")
        
        return results
    
    def update_dewu_price(
        self,
        result: PriceResult,
        dewu_price: float,
        buyers_count: int = None,
    ) -> PriceResult:
        """
        更新得物价格
        
        Args:
            result: 原价格结果
            dewu_price: 得物价格
            buyers_count: 付款人数
            
        Returns:
            更新后的价格结果
        """
        result.dewu_price = dewu_price
        result.dewu_net = round(dewu_price * (1 - result.commission_rate), 2)
        result.profit = round(result.dewu_net - result.taobao_final, 2)
        result.buyers_count = buyers_count
        
        logger.debug(f"更新得物价格: {result.article_no} - {dewu_price}, 利润 {result.profit}")
        
        return result
    
    def get_statistics(self, results: List[PriceResult]) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            results: 价格结果列表
            
        Returns:
            统计信息
        """
        total = len(results)
        profitable = sum(1 for r in results if r.profit and r.profit > 0)
        loss = sum(1 for r in results if r.profit and r.profit < 0)
        na = sum(1 for r in results if r.profit is None)
        
        profits = [r.profit for r in results if r.profit is not None]
        avg_profit = sum(profits) / len(profits) if profits else 0
        
        return {
            "total": total,
            "profitable": profitable,
            "loss": loss,
            "na": na,
            "avg_profit": round(avg_profit, 2),
        }


def create_calculator(
    coupon_str: str = None,
    jingou_charge: float = 2000,
    jingou_credit: float = 2100,
    commission_rate: float = 0.08,
    activity_deduct: float = 0,
) -> PriceCalculator:
    """
    创建价格计算器
    
    Args:
        coupon_str: 消费券字符串，如 "2000-200"
        jingou_charge: 购物金充值金额
        jingou_credit: 购物金到账金额
        commission_rate: 得物佣金率
        activity_deduct: 活动立减
        
    Returns:
        价格计算器实例
    """
    coupon = CouponConfig.parse(coupon_str) if coupon_str else None
    jingou = JingouConfig(charge=jingou_charge, credit=jingou_credit)
    
    return PriceCalculator(
        coupon=coupon,
        jingou=jingou,
        commission_rate=commission_rate,
        activity_deduct=activity_deduct,
    )


if __name__ == "__main__":
    calculator = create_calculator(
        coupon_str="2000-200",
        jingou_charge=2000,
        jingou_credit=2100,
        commission_rate=0.08,
        activity_deduct=0,
    )
    
    result = calculator.calculate_single(
        article_no="ABC123",
        taobao_listed=599,
        total_price=5000,
        dewu_price=699,
        buyers_count=128,
    )
    
    print(f"货号: {result.article_no}")
    print(f"淘宝到手价: {result.taobao_listed}")
    print(f"活动立减: {result.activity_deduct}")
    print(f"消费券分摊: {result.coupon_share}")
    print(f"购物金抵扣: {result.jingou_deduct}")
    print(f"淘宝最终成本: {result.taobao_final}")
    print(f"得物价格: {result.dewu_price}")
    print(f"得物扣佣后: {result.dewu_net}")
    print(f"差价利润: {result.profit}")
