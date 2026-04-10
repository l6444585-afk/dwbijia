"""
自适应令牌桶速率限制器

- 根据响应状态动态调整请求速率
- 被反爬时自动降速，正常时逐步提速
- 每个平台独立的速率控制
"""
import asyncio
import time
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class PlatformState:
    """单个平台的速率状态"""
    tokens: float = 5.0
    max_tokens: float = 10.0
    refill_rate: float = 1.0        # 每秒补充的令牌数
    min_refill_rate: float = 0.1    # 最低速率（被严重限制时）
    max_refill_rate: float = 3.0    # 最高速率
    last_refill: float = field(default_factory=time.time)
    consecutive_errors: int = 0
    consecutive_success: int = 0
    total_requests: int = 0
    total_blocked: int = 0
    last_request_time: float = 0
    min_interval: float = 1.0       # 最小请求间隔（秒）


class AdaptiveRateLimiter:
    """
    自适应速率限制器

    - 令牌桶算法控制并发
    - 根据成功/失败自动调整速率
    - 被封锁时指数退避
    """

    def __init__(self):
        self._states: dict[str, PlatformState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_state(self, platform: str) -> PlatformState:
        if platform not in self._states:
            self._states[platform] = PlatformState()
            self._locks[platform] = asyncio.Lock()
        return self._states[platform]

    async def acquire(self, platform: str) -> bool:
        """
        获取一个请求令牌

        阻塞直到有可用令牌，返回True
        如果等待超过60秒返回False
        """
        state = self._get_state(platform)
        lock = self._locks[platform]

        deadline = time.time() + 60
        while time.time() < deadline:
            async with lock:
                self._refill(state)
                if state.tokens >= 1.0:
                    state.tokens -= 1.0
                    # 确保最小请求间隔
                    now = time.time()
                    elapsed = now - state.last_request_time
                    if elapsed < state.min_interval:
                        await asyncio.sleep(state.min_interval - elapsed)
                    state.last_request_time = time.time()
                    state.total_requests += 1
                    return True
            await asyncio.sleep(0.5)

        logger.warning(f"[速率限制] {platform} 获取令牌超时")
        return False

    def report_success(self, platform: str):
        """报告请求成功 - 逐步提速"""
        state = self._get_state(platform)
        state.consecutive_errors = 0
        state.consecutive_success += 1

        # 连续成功10次，提速10%
        if state.consecutive_success % 10 == 0:
            old_rate = state.refill_rate
            state.refill_rate = min(state.refill_rate * 1.1, state.max_refill_rate)
            state.min_interval = max(state.min_interval * 0.95, 0.5)
            if state.refill_rate != old_rate:
                logger.debug(f"[速率限制] {platform} 提速: {old_rate:.2f} -> {state.refill_rate:.2f} req/s")

    def report_blocked(self, platform: str):
        """报告被封锁 - 指数退避降速"""
        state = self._get_state(platform)
        state.consecutive_success = 0
        state.consecutive_errors += 1
        state.total_blocked += 1

        # 指数退避
        old_rate = state.refill_rate
        backoff = min(2 ** state.consecutive_errors, 32)
        state.refill_rate = max(state.refill_rate / backoff, state.min_refill_rate)
        state.min_interval = min(state.min_interval * backoff, 30.0)

        logger.warning(
            f"[速率限制] {platform} 降速: {old_rate:.2f} -> {state.refill_rate:.2f} req/s "
            f"(连续失败{state.consecutive_errors}次, 间隔{state.min_interval:.1f}s)"
        )

    def report_error(self, platform: str):
        """报告普通错误（非反爬封锁）- 温和降速"""
        state = self._get_state(platform)
        state.consecutive_success = 0
        state.consecutive_errors += 1
        state.refill_rate = max(state.refill_rate * 0.8, state.min_refill_rate)

    def get_stats(self, platform: str) -> dict:
        """获取统计信息"""
        state = self._get_state(platform)
        return {
            "platform": platform,
            "current_rate": round(state.refill_rate, 3),
            "tokens_available": round(state.tokens, 1),
            "min_interval": round(state.min_interval, 2),
            "total_requests": state.total_requests,
            "total_blocked": state.total_blocked,
            "block_rate": round(state.total_blocked / max(state.total_requests, 1) * 100, 1),
            "consecutive_errors": state.consecutive_errors,
        }

    def _refill(self, state: PlatformState):
        """补充令牌"""
        now = time.time()
        elapsed = now - state.last_refill
        state.tokens = min(state.tokens + elapsed * state.refill_rate, state.max_tokens)
        state.last_refill = now
