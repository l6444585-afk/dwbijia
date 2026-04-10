"""
第三方聚合API模块

提供大淘客、好单库等第三方优惠商品API的统一接入，
用于补充爬虫数据源，获取优惠券、佣金等附加信息。
"""

from app.scrapers.apis.dataoke import DataokeAPI
from app.scrapers.apis.haodanku import HaodankuAPI
from app.scrapers.apis.aggregator import PriceAggregator

__all__ = [
    "DataokeAPI",
    "HaodankuAPI",
    "PriceAggregator",
]
