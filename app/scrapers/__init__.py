from app.scrapers.base import BaseScraper
from app.scrapers.taobao import TaobaoScraper
from app.scrapers.dewu import DewuScraper
from app.scrapers.platforms.taobao_real import TaobaoRealScraper
from app.scrapers.platforms.dewu_real import DewuRealScraper
from app.scrapers.sdk.client import scraper_client

__all__ = [
    "BaseScraper",
    "TaobaoScraper",
    "DewuScraper",
    "TaobaoRealScraper",
    "DewuRealScraper",
    "scraper_client",
]
