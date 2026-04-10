"""
系统健康监控

- 跟踪爬虫运行状态
- 自动检测异常并恢复
- 记录MTBF（平均无故障时间）
"""
import asyncio
import time
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class PlatformHealth:
    """单个平台的健康状态"""
    platform: str
    is_healthy: bool = True
    last_success_time: float = 0
    last_failure_time: float = 0
    uptime_start: float = field(default_factory=time.time)
    downtime_periods: list = field(default_factory=list)  # [(start, end), ...]
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0


class HealthMonitor:
    """
    爬虫系统健康监控

    功能:
    - 跟踪每个平台的健康状态
    - 连续失败自动标记为不健康
    - 自动恢复检测
    - 计算 MTBF（平均无故障时间）
    """

    # 连续失败多少次标记为不健康
    FAILURE_THRESHOLD = 5
    # 不健康后多久尝试恢复检查（秒）
    RECOVERY_CHECK_INTERVAL = 120

    def __init__(self):
        self._platforms: dict[str, PlatformHealth] = {}
        self._start_time = time.time()
        self._alerts: list[dict] = []

    def _get(self, platform: str) -> PlatformHealth:
        if platform not in self._platforms:
            self._platforms[platform] = PlatformHealth(platform=platform)
        return self._platforms[platform]

    def report_success(self, platform: str):
        """报告成功"""
        state = self._get(platform)
        state.total_checks += 1
        state.last_success_time = time.time()
        state.consecutive_failures = 0

        if not state.is_healthy:
            # 恢复健康
            state.is_healthy = True
            if state.downtime_periods and state.downtime_periods[-1][1] == 0:
                state.downtime_periods[-1] = (state.downtime_periods[-1][0], time.time())
            logger.info(f"[健康监控] {platform} 已恢复健康")
            self._add_alert(platform, "recovery", f"{platform} 爬虫已恢复正常")

    def report_failure(self, platform: str, error: str = ""):
        """报告失败"""
        state = self._get(platform)
        state.total_checks += 1
        state.total_failures += 1
        state.last_failure_time = time.time()
        state.consecutive_failures += 1

        if state.is_healthy and state.consecutive_failures >= self.FAILURE_THRESHOLD:
            state.is_healthy = False
            state.downtime_periods.append((time.time(), 0))
            logger.error(
                f"[健康监控] {platform} 标记为不健康 "
                f"(连续失败 {state.consecutive_failures} 次: {error})"
            )
            self._add_alert(platform, "down", f"{platform} 爬虫连续失败 {state.consecutive_failures} 次: {error}")

    def is_healthy(self, platform: str) -> bool:
        """检查平台是否健康"""
        state = self._get(platform)
        return state.is_healthy

    def should_retry(self, platform: str) -> bool:
        """
        不健康平台是否应该重试

        到了恢复检查间隔时返回True
        """
        state = self._get(platform)
        if state.is_healthy:
            return True
        elapsed = time.time() - state.last_failure_time
        return elapsed >= self.RECOVERY_CHECK_INTERVAL

    def get_mtbf(self, platform: str) -> float:
        """
        计算MTBF（平均无故障时间），单位：小时

        MTBF = 总运行时间 / 故障次数
        """
        state = self._get(platform)
        total_time = (time.time() - self._start_time) / 3600  # 转为小时
        fault_count = len(state.downtime_periods)
        if fault_count == 0:
            return total_time  # 无故障
        return total_time / fault_count

    def get_availability(self, platform: str) -> float:
        """计算可用率（%）"""
        state = self._get(platform)
        total_time = time.time() - self._start_time
        if total_time <= 0:
            return 100.0

        downtime = 0
        for start, end in state.downtime_periods:
            end_time = end if end > 0 else time.time()
            downtime += end_time - start

        uptime = total_time - downtime
        return round(uptime / total_time * 100, 2)

    def get_status(self, platform: str = "") -> dict:
        """获取健康状态报告"""
        if platform:
            state = self._get(platform)
            return {
                "platform": platform,
                "is_healthy": state.is_healthy,
                "consecutive_failures": state.consecutive_failures,
                "total_checks": state.total_checks,
                "failure_rate": round(state.total_failures / max(state.total_checks, 1) * 100, 1),
                "mtbf_hours": round(self.get_mtbf(platform), 2),
                "availability": self.get_availability(platform),
                "last_success": state.last_success_time,
                "last_failure": state.last_failure_time,
            }
        else:
            return {
                p: self.get_status(p) for p in self._platforms
            }

    def get_alerts(self, limit: int = 50) -> list[dict]:
        """获取最近的告警"""
        return self._alerts[-limit:]

    def _add_alert(self, platform: str, alert_type: str, message: str):
        self._alerts.append({
            "platform": platform,
            "type": alert_type,
            "message": message,
            "time": time.time(),
        })
        # 保留最近100条
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]
