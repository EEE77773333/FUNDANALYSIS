"""
AI 预测校准指标 — 方向命中、Brier、ECE
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def direction_hit(action: str, actual_return: float) -> Optional[bool]:
    """
    判断方向是否命中。
    返回 True/False；中性动作波动过大返回 None（记为 partial，不计入方向准确率分子）。
    """
    action = (action or "hold").lower()
    bullish = action in ("buy", "add")
    bearish = action in ("sell", "reduce", "avoid")
    neutral = action in ("hold", "watch")

    if neutral:
        if abs(actual_return) < 0.02:
            return True
        if abs(actual_return) < 0.05:
            return None
        return False

    if bullish:
        if actual_return > 0.03:
            return True
        if actual_return > -0.02:
            return None
        return False

    if bearish:
        if actual_return < -0.03:
            return True
        if actual_return < 0.02:
            return None
        return False

    return None


def outcome_label(action: str, actual_return: float) -> str:
    hit = direction_hit(action, actual_return)
    if hit is True:
        return "correct"
    if hit is False:
        return "wrong"
    return "partial"


def brier_score(confidence: float, hit: Optional[bool]) -> float:
    """Brier 分数；partial 按 0.5 处理。"""
    conf = max(0.0, min(1.0, float(confidence or 0)))
    if hit is True:
        target = 1.0
    elif hit is False:
        target = 0.0
    else:
        target = 0.5
    return (conf - target) ** 2


def expected_calibration_error(
    pairs: List[Tuple[float, bool]],
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error（仅使用明确 hit 样本）。"""
    if not pairs:
        return 0.0
    bins: Dict[int, List[Tuple[float, bool]]] = {i: [] for i in range(n_bins)}
    for conf, hit in pairs:
        idx = min(n_bins - 1, int(conf * n_bins))
        bins[idx].append((conf, hit))

    total = len(pairs)
    ece = 0.0
    for items in bins.values():
        if not items:
            continue
        avg_conf = sum(c for c, _ in items) / len(items)
        avg_acc = sum(1.0 if h else 0.0 for _, h in items) / len(items)
        ece += (len(items) / total) * abs(avg_conf - avg_acc)
    return round(ece, 4)


def calibration_buckets(
    evaluations: List[dict],
    n_bins: int = 5,
) -> List[dict]:
    """分桶校准数据：置信度区间 vs 实际命中率。"""
    buckets: Dict[int, dict] = {}
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        buckets[i] = {
            "bin": f"{lo:.0%}-{hi:.0%}",
            "count": 0,
            "avg_confidence": 0.0,
            "hit_rate": 0.0,
        }

    for ev in evaluations:
        hit = ev.get("direction_hit")
        if hit is None:
            continue
        conf = float(ev.get("confidence") or 0)
        idx = min(n_bins - 1, int(conf * n_bins))
        b = buckets[idx]
        b["count"] += 1
        b["avg_confidence"] += conf
        b["hit_rate"] += 1.0 if hit else 0.0

    result = []
    for b in buckets.values():
        if b["count"] > 0:
            b["avg_confidence"] = round(b["avg_confidence"] / b["count"], 4)
            b["hit_rate"] = round(b["hit_rate"] / b["count"], 4)
        result.append(b)
    return result


def aggregate_metrics(evaluations: List[dict]) -> dict:
    """汇总 KPI。"""
    if not evaluations:
        return {
            "total": 0,
            "direction_accuracy": 0.0,
            "avg_brier": 0.0,
            "ece": 0.0,
            "by_horizon": {},
            "by_action": {},
        }

    decisive = [e for e in evaluations if e.get("direction_hit") is not None]
    hits = sum(1 for e in decisive if e.get("direction_hit"))
    accuracy = hits / len(decisive) if decisive else 0.0
    avg_brier = sum(float(e.get("brier_score") or 0) for e in evaluations) / len(evaluations)

    pairs = [(float(e["confidence"]), bool(e["direction_hit"])) for e in decisive]
    ece = expected_calibration_error(pairs)

    by_horizon: Dict[int, dict] = {}
    for e in evaluations:
        h = int(e.get("horizon_days") or 0)
        if h not in by_horizon:
            by_horizon[h] = {"total": 0, "hits": 0, "decisive": 0}
        by_horizon[h]["total"] += 1
        if e.get("direction_hit") is not None:
            by_horizon[h]["decisive"] += 1
            if e.get("direction_hit"):
                by_horizon[h]["hits"] += 1

    for h, v in by_horizon.items():
        v["accuracy"] = round(v["hits"] / v["decisive"], 4) if v["decisive"] else 0.0

    by_action: Dict[str, int] = {}
    for e in evaluations:
        a = e.get("predicted_action") or "hold"
        by_action[a] = by_action.get(a, 0) + 1

    return {
        "total": len(evaluations),
        "direction_accuracy": round(accuracy, 4),
        "avg_brier": round(avg_brier, 4),
        "ece": ece,
        "by_horizon": by_horizon,
        "by_action": by_action,
    }
