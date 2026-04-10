"""
反爬虫检测与应对引擎

识别反爬类型 → 选择应对策略 → 执行 → 评估效果
"""
import asyncio
import time
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


class BlockType(Enum):
    """反爬类型分类"""
    NONE = "none"
    RATE_LIMIT = "rate_limit"           # 请求频率限制 (429/503)
    IP_BLOCK = "ip_block"               # IP封锁 (403)
    UA_BLOCK = "ua_block"               # User-Agent 检测
    CAPTCHA = "captcha"                 # 验证码 (滑动/点选/图片)
    JS_CHALLENGE = "js_challenge"       # JavaScript 人机验证
    LOGIN_REQUIRED = "login_required"   # 需要登录
    EMPTY_RESPONSE = "empty_response"   # 返回空页面/假数据
    REDIRECT = "redirect"               # 重定向到验证页


class Strategy(Enum):
    """应对策略"""
    RETRY_DELAY = "retry_delay"             # 等待后重试
    SWITCH_PROXY = "switch_proxy"           # 切换代理IP
    SWITCH_UA = "switch_ua"                 # 切换User-Agent
    USE_BROWSER = "use_browser"             # 切换到浏览器模式
    ROTATE_FINGERPRINT = "rotate_fingerprint"  # 更换完整指纹
    SOLVE_CAPTCHA = "solve_captcha"         # 验证码识别
    USE_COOKIE = "use_cookie"               # 使用预登录Cookie
    BACKOFF = "backoff"                     # 指数退避


# 每种反爬类型对应的应对策略（按优先级排列）
STRATEGY_MAP: dict[BlockType, list[Strategy]] = {
    BlockType.RATE_LIMIT: [Strategy.RETRY_DELAY, Strategy.SWITCH_PROXY, Strategy.BACKOFF],
    BlockType.IP_BLOCK: [Strategy.SWITCH_PROXY, Strategy.ROTATE_FINGERPRINT, Strategy.BACKOFF],
    BlockType.UA_BLOCK: [Strategy.SWITCH_UA, Strategy.ROTATE_FINGERPRINT, Strategy.USE_BROWSER],
    BlockType.CAPTCHA: [Strategy.SOLVE_CAPTCHA, Strategy.SWITCH_PROXY, Strategy.USE_BROWSER],
    BlockType.JS_CHALLENGE: [Strategy.USE_BROWSER, Strategy.ROTATE_FINGERPRINT, Strategy.RETRY_DELAY],
    BlockType.LOGIN_REQUIRED: [Strategy.USE_COOKIE, Strategy.USE_BROWSER, Strategy.BACKOFF],
    BlockType.EMPTY_RESPONSE: [Strategy.USE_BROWSER, Strategy.SWITCH_PROXY, Strategy.RETRY_DELAY],
    BlockType.REDIRECT: [Strategy.USE_BROWSER, Strategy.SWITCH_PROXY, Strategy.ROTATE_FINGERPRINT],
}


@dataclass
class DetectionResult:
    """检测结果"""
    block_type: BlockType
    confidence: float = 0.0   # 检测置信度 0~1
    detail: str = ""
    strategies: list[Strategy] = field(default_factory=list)


@dataclass
class StrategyResult:
    """策略执行结果"""
    strategy: Strategy
    success: bool
    latency: float = 0.0
    detail: str = ""


class AntiDetectEngine:
    """
    反爬虫检测与应对引擎

    工作流程:
    1. detect() 分析响应，识别反爬类型
    2. get_strategies() 返回应对策略列表
    3. 调用方执行策略
    4. report_result() 记录策略效果
    """

    def __init__(self):
        # 策略效果统计: {platform: {strategy: {success: n, fail: n}}}
        self._stats: dict = {}

    def detect(self, status_code: int, body: str = "", url: str = "", headers: dict = None) -> DetectionResult:
        """
        分析HTTP响应，识别反爬虫类型

        Args:
            status_code: HTTP状态码
            body: 响应体文本
            url: 请求URL
            headers: 响应头
        """
        headers = headers or {}
        body_lower = body.lower() if body else ""

        # 1. HTTP状态码判断
        if status_code == 429:
            return DetectionResult(
                block_type=BlockType.RATE_LIMIT,
                confidence=0.95,
                detail="HTTP 429 Too Many Requests",
                strategies=STRATEGY_MAP[BlockType.RATE_LIMIT],
            )

        if status_code == 403:
            return DetectionResult(
                block_type=BlockType.IP_BLOCK,
                confidence=0.85,
                detail="HTTP 403 Forbidden",
                strategies=STRATEGY_MAP[BlockType.IP_BLOCK],
            )

        if status_code in (301, 302, 307):
            location = headers.get("location", "")
            if "login" in location or "sign" in location:
                return DetectionResult(
                    block_type=BlockType.LOGIN_REQUIRED,
                    confidence=0.9,
                    detail=f"重定向到登录页: {location}",
                    strategies=STRATEGY_MAP[BlockType.LOGIN_REQUIRED],
                )
            if "captcha" in location or "verify" in location or "sec" in location:
                return DetectionResult(
                    block_type=BlockType.CAPTCHA,
                    confidence=0.9,
                    detail=f"重定向到验证页: {location}",
                    strategies=STRATEGY_MAP[BlockType.CAPTCHA],
                )

        if status_code == 503:
            return DetectionResult(
                block_type=BlockType.RATE_LIMIT,
                confidence=0.7,
                detail="HTTP 503 Service Unavailable (可能限流)",
                strategies=STRATEGY_MAP[BlockType.RATE_LIMIT],
            )

        # 2. 响应体内容判断
        if status_code == 200 and body_lower:
            # 验证码检测
            captcha_patterns = [
                r"验证码", r"captcha", r"slider.*verify", r"滑动验证",
                r"nc_wrapper", r"baxia", r"punish", r"antibot",
                r"验证中心", r"security.*check",
            ]
            for pat in captcha_patterns:
                if re.search(pat, body_lower):
                    return DetectionResult(
                        block_type=BlockType.CAPTCHA,
                        confidence=0.85,
                        detail=f"页面包含验证码特征: {pat}",
                        strategies=STRATEGY_MAP[BlockType.CAPTCHA],
                    )

            # 登录要求检测
            login_patterns = [r"请登录", r"login.*required", r"请先登录", r"sign.*in"]
            for pat in login_patterns:
                if re.search(pat, body_lower):
                    return DetectionResult(
                        block_type=BlockType.LOGIN_REQUIRED,
                        confidence=0.85,
                        detail=f"页面要求登录: {pat}",
                        strategies=STRATEGY_MAP[BlockType.LOGIN_REQUIRED],
                    )

            # JS挑战检测
            js_patterns = [r"challenge.*platform", r"<noscript>", r"javascript.*required", r"__cf_chl"]
            for pat in js_patterns:
                if re.search(pat, body_lower):
                    return DetectionResult(
                        block_type=BlockType.JS_CHALLENGE,
                        confidence=0.8,
                        detail=f"JS人机验证: {pat}",
                        strategies=STRATEGY_MAP[BlockType.JS_CHALLENGE],
                    )

            # 空响应检测 - 页面有HTML框架但无商品数据
            if len(body) < 500 and "<html" in body_lower:
                return DetectionResult(
                    block_type=BlockType.EMPTY_RESPONSE,
                    confidence=0.6,
                    detail="响应体过小，可能返回了空页面",
                    strategies=STRATEGY_MAP[BlockType.EMPTY_RESPONSE],
                )

        # 无异常
        return DetectionResult(block_type=BlockType.NONE, confidence=0.0)

    def get_strategies(self, block_type: BlockType) -> list[Strategy]:
        """获取对应的应对策略"""
        return STRATEGY_MAP.get(block_type, [Strategy.RETRY_DELAY])

    def report_result(self, platform: str, strategy: Strategy, success: bool):
        """记录策略执行效果"""
        if platform not in self._stats:
            self._stats[platform] = {}
        key = strategy.value
        if key not in self._stats[platform]:
            self._stats[platform][key] = {"success": 0, "fail": 0}
        if success:
            self._stats[platform][key]["success"] += 1
        else:
            self._stats[platform][key]["fail"] += 1

    def get_strategy_stats(self, platform: str = "") -> dict:
        """获取策略效果统计"""
        if platform:
            raw = self._stats.get(platform, {})
            result = {}
            for s, counts in raw.items():
                total = counts["success"] + counts["fail"]
                result[s] = {
                    **counts,
                    "total": total,
                    "success_rate": round(counts["success"] / max(total, 1) * 100, 1),
                }
            return {platform: result}
        else:
            all_stats = {}
            for p in self._stats:
                all_stats.update(self.get_strategy_stats(p))
            return all_stats

    def recommend_strategy(self, platform: str, block_type: BlockType) -> Strategy:
        """根据历史效果推荐最优策略"""
        strategies = self.get_strategies(block_type)
        if not strategies:
            return Strategy.RETRY_DELAY

        stats = self._stats.get(platform, {})
        best_strategy = strategies[0]
        best_rate = -1

        for s in strategies:
            counts = stats.get(s.value, {"success": 0, "fail": 0})
            total = counts["success"] + counts["fail"]
            if total == 0:
                # 未尝试过的策略给予中等优先级
                rate = 0.5
            else:
                rate = counts["success"] / total
            if rate > best_rate:
                best_rate = rate
                best_strategy = s

        return best_strategy
