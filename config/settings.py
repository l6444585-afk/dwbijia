from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "跨平台智能比价系统"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./dwbijia.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ALGORITHM: str = "HS256"

    # ============================================
    # 淘宝API - 请填入你的API密钥
    # 申请地址: https://open.taobao.com/
    # ============================================
    TAOBAO_API_KEY: Optional[str] = None
    TAOBAO_API_SECRET: Optional[str] = None
    TAOBAO_API_URL: Optional[str] = None

    # ============================================
    # 京东API - 请填入你的API密钥
    # 申请地址: https://union.jd.com/
    # ============================================
    JD_API_KEY: Optional[str] = None
    JD_API_SECRET: Optional[str] = None
    JD_API_URL: Optional[str] = None

    # ============================================
    # 得物API - 请填入你的API密钥
    # ============================================
    DEWU_API_KEY: Optional[str] = None
    DEWU_API_SECRET: Optional[str] = None
    DEWU_API_URL: Optional[str] = None

    # ============================================
    # 拼多多API - 请填入你的API密钥
    # 申请地址: https://open.pinduoduo.com/
    # ============================================
    PDD_API_KEY: Optional[str] = None
    PDD_API_SECRET: Optional[str] = None
    PDD_API_URL: Optional[str] = None

    # ============================================
    # 1688(阿里巴巴批发)API - 请填入你的API密钥
    # 申请地址: https://open.1688.com/
    # ============================================
    ALI1688_API_KEY: Optional[str] = None
    ALI1688_API_SECRET: Optional[str] = None
    ALI1688_API_URL: Optional[str] = None

    # ============================================
    # 识货API - 请填入你的API密钥
    # ============================================
    SHIHUO_API_KEY: Optional[str] = None
    SHIHUO_API_SECRET: Optional[str] = None
    SHIHUO_API_URL: Optional[str] = None

    # ============================================
    # 大淘客API - 第三方优惠商品聚合
    # 申请地址: https://www.dataoke.com/openapi
    # ============================================
    DATAOKE_APP_KEY: Optional[str] = None
    DATAOKE_APP_SECRET: Optional[str] = None

    # ============================================
    # 好单库API - 第三方优惠商品聚合
    # 申请地址: https://www.haodanku.com/openapi
    # ============================================
    HAODANKU_API_KEY: Optional[str] = None

    # 通知 - 邮件
    SMTP_HOST: str = "smtp.qq.com"
    SMTP_PORT: int = 465
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None

    # 通知 - 短信(阿里云)
    SMS_ACCESS_KEY: Optional[str] = None
    SMS_ACCESS_SECRET: Optional[str] = None
    SMS_SIGN_NAME: Optional[str] = None
    SMS_TEMPLATE_CODE: Optional[str] = None

    # 爬虫基础
    CRAWL_DELAY: float = 2.0
    MAX_REQUESTS_PER_HOUR: int = 500
    USER_AGENT: str = "Mozilla/5.0 (compatible; PriceBot/1.0)"

    # ============================================
    # 代理池 - 可选，不配置则直连
    # ============================================
    # 付费代理API地址（快代理/芝麻代理/站大爷等）
    PROXY_API_URL: Optional[str] = None
    PROXY_API_KEY: Optional[str] = None
    # 静态代理列表，逗号分隔: http://ip:port,http://ip:port
    PROXY_LIST: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
