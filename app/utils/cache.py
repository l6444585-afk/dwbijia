"""
Redis缓存工具

无Redis时自动降级为内存缓存
"""
import json
import time
from typing import Optional, Any
from loguru import logger

# 内存缓存（Redis不可用时的降级方案）
_memory_cache: dict = {}


class CacheManager:
    """缓存管理器"""

    def __init__(self):
        self.redis = None
        self._try_connect()

    def _try_connect(self):
        """尝试连接Redis"""
        try:
            import redis as redis_lib
            from config.settings import settings
            self.redis = redis_lib.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            self.redis.ping()
            logger.info("[缓存] Redis连接成功")
        except Exception:
            self.redis = None
            logger.info("[缓存] Redis不可用，使用内存缓存")

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        try:
            if self.redis:
                val = self.redis.get(key)
                return json.loads(val) if val else None
            else:
                item = _memory_cache.get(key)
                if item and item["expire"] > time.time():
                    return item["value"]
                elif item:
                    del _memory_cache[key]
                return None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = 300):
        """设置缓存 (默认5分钟)"""
        try:
            if self.redis:
                self.redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
            else:
                _memory_cache[key] = {
                    "value": value,
                    "expire": time.time() + ttl,
                }
        except Exception:
            pass

    async def delete(self, key: str):
        """删除缓存"""
        try:
            if self.redis:
                self.redis.delete(key)
            else:
                _memory_cache.pop(key, None)
        except Exception:
            pass


cache = CacheManager()
