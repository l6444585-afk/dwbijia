"""
数据质量监控

- 价格合理性校验
- 异常数据自动标记
- 数据完整性检查
"""
import time
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class QualityStats:
    """质量统计"""
    total_checked: int = 0
    passed: int = 0
    flagged_price_anomaly: int = 0
    flagged_missing_data: int = 0
    flagged_duplicate: int = 0


class DataQualityChecker:
    """
    数据质量检查器

    校验规则:
    1. 价格合理性: 是否在合理范围内（1元 ~ 100万）
    2. 价格异常波动: 与历史价格对比是否偏差过大（>50%）
    3. 数据完整性: 必填字段是否存在
    4. 重复数据: 同一平台同一ID是否重复
    """

    PRICE_MIN = 1.0
    PRICE_MAX = 1_000_000.0
    MAX_PRICE_CHANGE_RATIO = 0.5  # 最大价格波动50%

    def __init__(self):
        self._stats = QualityStats()
        # 缓存最近的价格用于波动检测: {platform_id: price}
        self._price_cache: dict[str, float] = {}
        # 最近处理的ID用于去重
        self._recent_ids: set[str] = set()

    def check(self, item: dict) -> dict:
        """
        检查单条商品数据质量

        Returns:
            {
                "valid": bool,
                "issues": ["issue1", "issue2"],
                "item": 原始或修正后的item
            }
        """
        self._stats.total_checked += 1
        issues = []

        # 1. 数据完整性
        required_fields = ["platform", "platform_id", "title", "price"]
        for f in required_fields:
            if not item.get(f):
                issues.append(f"缺少必填字段: {f}")
                self._stats.flagged_missing_data += 1

        # 2. 价格合理性
        price = item.get("price", 0)
        if price < self.PRICE_MIN:
            issues.append(f"价格过低: ¥{price}")
            self._stats.flagged_price_anomaly += 1
        elif price > self.PRICE_MAX:
            issues.append(f"价格过高: ¥{price}")
            self._stats.flagged_price_anomaly += 1

        # 3. 原价不应低于现价（如果有原价）
        original = item.get("original_price")
        if original and original > 0 and price > 0:
            if price > original * 1.5:
                issues.append(f"现价 ¥{price} 远高于原价 ¥{original}")

        # 4. 价格异常波动
        cache_key = f"{item.get('platform')}:{item.get('platform_id')}"
        if cache_key in self._price_cache:
            old_price = self._price_cache[cache_key]
            if old_price > 0 and price > 0:
                change_ratio = abs(price - old_price) / old_price
                if change_ratio > self.MAX_PRICE_CHANGE_RATIO:
                    issues.append(
                        f"价格波动异常: ¥{old_price} -> ¥{price} "
                        f"(变化 {change_ratio:.0%})"
                    )
                    self._stats.flagged_price_anomaly += 1

        # 更新价格缓存
        if price > 0:
            self._price_cache[cache_key] = price

        # 5. 重复检测
        if cache_key in self._recent_ids:
            issues.append("重复数据")
            self._stats.flagged_duplicate += 1
        self._recent_ids.add(cache_key)
        # 保持集合大小可控
        if len(self._recent_ids) > 10000:
            self._recent_ids = set(list(self._recent_ids)[-5000:])

        if not issues:
            self._stats.passed += 1

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "item": item,
        }

    def check_batch(self, items: list[dict]) -> dict:
        """
        批量检查

        Returns:
            {
                "valid_items": [...],
                "invalid_items": [{item, issues}, ...],
                "summary": {total, valid, invalid}
            }
        """
        valid = []
        invalid = []

        for item in items:
            result = self.check(item)
            if result["valid"]:
                valid.append(item)
            else:
                invalid.append({"item": item, "issues": result["issues"]})

        if invalid:
            logger.warning(
                f"[数据质量] 批量检查: {len(valid)}/{len(items)} 通过, "
                f"{len(invalid)} 个异常"
            )

        return {
            "valid_items": valid,
            "invalid_items": invalid,
            "summary": {
                "total": len(items),
                "valid": len(valid),
                "invalid": len(invalid),
                "pass_rate": round(len(valid) / max(len(items), 1) * 100, 1),
            },
        }

    def get_stats(self) -> dict:
        s = self._stats
        return {
            "total_checked": s.total_checked,
            "passed": s.passed,
            "pass_rate": round(s.passed / max(s.total_checked, 1) * 100, 1),
            "flagged_price_anomaly": s.flagged_price_anomaly,
            "flagged_missing_data": s.flagged_missing_data,
            "flagged_duplicate": s.flagged_duplicate,
            "price_cache_size": len(self._price_cache),
        }
