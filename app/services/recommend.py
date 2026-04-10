"""
智能推荐服务 - 基于价格差异、优惠力度的推荐排序
"""
from typing import Optional


class RecommendService:
    """推荐引擎"""

    def rank_by_value(self, matched_items: list) -> list:
        """
        按综合性价比排序

        考虑因素:
        - 价差百分比 (权重最高)
        - 销量 (热度参考)
        - 评分 (质量参考)
        """
        scored = []
        for item in matched_items:
            score = self._calc_value_score(item)
            scored.append({**item, "value_score": score})

        scored.sort(key=lambda x: x["value_score"], reverse=True)
        return scored

    def _calc_value_score(self, matched: dict) -> float:
        """计算综合价值分数 (0~100)"""
        score = 0.0

        # 价差得分 (0~40分)：差价越大越划算
        save_pct = matched.get("save_percent", 0)
        score += min(save_pct * 2, 40)

        # 选择更便宜的那个平台的商品来评估
        cheaper = matched.get("cheaper_platform", "same")
        item = matched.get(cheaper, matched.get("taobao", {}))

        # 销量得分 (0~30分)
        sales = item.get("sales", 0)
        if sales > 10000:
            score += 30
        elif sales > 5000:
            score += 25
        elif sales > 1000:
            score += 20
        elif sales > 100:
            score += 10

        # 评分得分 (0~20分)
        rating = item.get("rating", 0)
        score += max(0, (rating - 3.0)) * 10  # 3分以上才加分

        # 降价幅度得分 (0~10分)
        original = item.get("original_price", 0)
        current = item.get("price", 0)
        if original > 0 and current > 0 and original > current:
            discount = (original - current) / original * 100
            score += min(discount / 5, 10)

        return round(score, 1)

    def get_best_deals(self, compare_result: dict, top_n: int = 5) -> list:
        """获取最优惠的N个商品"""
        matched = compare_result.get("matched", [])
        ranked = self.rank_by_value(matched)
        return ranked[:top_n]

    def get_platform_recommendation(self, compare_result: dict) -> dict:
        """
        给出平台推荐建议
        """
        stats = compare_result.get("stats", {})
        matched = compare_result.get("matched", [])

        tb_wins = stats.get("taobao_cheaper_count", 0)
        dw_wins = stats.get("dewu_cheaper_count", 0)
        total = len(matched)

        if total == 0:
            return {"recommendation": "数据不足，无法推荐", "confidence": 0}

        if tb_wins > dw_wins:
            platform = "taobao"
            name = "淘宝"
            pct = round(tb_wins / total * 100, 1)
        elif dw_wins > tb_wins:
            platform = "dewu"
            name = "得物"
            pct = round(dw_wins / total * 100, 1)
        else:
            return {
                "recommendation": "两个平台价格相近，建议根据品质和服务选择",
                "platform": "tie",
                "confidence": 50,
            }

        return {
            "recommendation": f"推荐在{name}购买，该搜索中{pct}%的匹配商品在{name}更便宜",
            "platform": platform,
            "win_count": max(tb_wins, dw_wins),
            "total_matched": total,
            "avg_save": round(
                sum(m["price_diff"] for m in matched if m["cheaper_platform"] == platform) /
                max(1, sum(1 for m in matched if m["cheaper_platform"] == platform)),
                2,
            ),
            "confidence": round(max(tb_wins, dw_wins) / total * 100, 1),
        }
