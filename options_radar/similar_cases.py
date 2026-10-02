from __future__ import annotations

import math
from statistics import median
from typing import Any


MIN_SIMILAR_SAMPLE = 10
DEFAULT_TOP_K = 20


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _tier_value(value: Any) -> float:
    return {
        "A+": 100.0,
        "A": 90.0,
        "B": 75.0,
        "C": 55.0,
        "X": 0.0,
    }.get(str(value or "").upper(), 50.0)


def _target_distance_pct(
    *,
    entry: float,
    target: float,
) -> float | None:
    if entry <= 0 or target <= 0:
        return None
    return abs(target - entry) / entry * 100.0


def _current_features(opportunity: dict[str, Any]) -> dict[str, Any]:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    t1 = target_map.get("t1") if isinstance(target_map.get("t1"), dict) else {}
    horizon = opportunity.get("target_horizon") if isinstance(opportunity.get("target_horizon"), dict) else {}
    cause = opportunity.get("explosion_cause") if isinstance(opportunity.get("explosion_cause"), dict) else {}
    entry = _number(opportunity.get("price"))
    target = _number(t1.get("price"))
    return {
        "direction": str(opportunity.get("direction") or "").upper(),
        "primary_horizon": str(horizon.get("primary_horizon") or "UNKNOWN"),
        "explosion_cause": str(cause.get("primary") or "UNKNOWN"),
        "opportunity_tier": str(opportunity.get("opportunity_tier") or ""),
        "explosion_rank": _number(opportunity.get("explosion_rank")),
        "t1_distance_pct": _target_distance_pct(entry=entry, target=target),
    }


def _historical_features(signal: dict[str, Any]) -> dict[str, Any]:
    targets = signal.get("targets") if isinstance(signal.get("targets"), dict) else {}
    t1 = targets.get("T1") if isinstance(targets.get("T1"), dict) else {}
    entry = _number(signal.get("entry_price"))
    target = _number(t1.get("price"))
    return {
        "direction": str(signal.get("direction") or "").upper(),
        "primary_horizon": str(signal.get("primary_horizon") or t1.get("horizon_bucket") or "UNKNOWN"),
        "explosion_cause": str(signal.get("explosion_cause") or "UNKNOWN"),
        "opportunity_tier": str(signal.get("opportunity_tier") or ""),
        "explosion_rank": _number(signal.get("explosion_rank")),
        "t1_distance_pct": _target_distance_pct(entry=entry, target=target),
        "t1": t1,
    }


def _similarity(current: dict[str, Any], historical: dict[str, Any]) -> tuple[float, list[str]]:
    if current["direction"] != historical["direction"]:
        return 0.0, ["direction_mismatch"]

    score = 30.0
    reasons = ["same_direction"]

    if current["primary_horizon"] == historical["primary_horizon"]:
        score += 24.0
        reasons.append("same_horizon")
    elif "UNKNOWN" not in {current["primary_horizon"], historical["primary_horizon"]}:
        score -= 8.0

    if (
        current["explosion_cause"] == historical["explosion_cause"]
        and current["explosion_cause"] != "UNKNOWN"
    ):
        score += 18.0
        reasons.append("same_explosion_cause")

    rank_gap = abs(current["explosion_rank"] - historical["explosion_rank"])
    score += max(0.0, 14.0 - rank_gap * 0.7)
    if rank_gap <= 8:
        reasons.append("similar_rank")

    tier_gap = abs(
        _tier_value(current["opportunity_tier"])
        - _tier_value(historical["opportunity_tier"])
    )
    score += max(0.0, 7.0 - tier_gap * 0.2)
    if tier_gap <= 15:
        reasons.append("similar_tier")

    current_distance = current.get("t1_distance_pct")
    old_distance = historical.get("t1_distance_pct")
    if current_distance is not None and old_distance is not None:
        gap = abs(float(current_distance) - float(old_distance))
        score += max(0.0, 12.0 - gap * 2.0)
        if gap <= 2.5:
            reasons.append("similar_t1_distance")

    return max(0.0, min(100.0, score)), reasons


def find_similar_cases(
    opportunity: dict[str, Any],
    target_state: dict[str, Any] | None,
    *,
    top_k: int = DEFAULT_TOP_K,
    minimum_sample: int = MIN_SIMILAR_SAMPLE,
) -> dict[str, Any]:
    state = target_state if isinstance(target_state, dict) else {}
    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    current = _current_features(opportunity)

    ranked: list[dict[str, Any]] = []
    for signal in signals.values():
        if not isinstance(signal, dict):
            continue
        hist = _historical_features(signal)
        t1 = hist["t1"]
        if not isinstance(t1, dict) or t1.get("matured") is not True:
            continue
        similarity, reasons = _similarity(current, hist)
        if similarity < 55.0:
            continue
        ranked.append(
            {
                "signal_id": signal.get("signal_id"),
                "symbol": signal.get("symbol"),
                "signal_time": signal.get("signal_time"),
                "similarity": round(similarity, 1),
                "similarity_reasons": reasons,
                "direction": hist["direction"],
                "primary_horizon": hist["primary_horizon"],
                "explosion_cause": hist["explosion_cause"],
                "opportunity_tier": hist["opportunity_tier"],
                "explosion_rank": hist["explosion_rank"],
                "t1_distance_pct": (
                    round(float(hist["t1_distance_pct"]), 2)
                    if hist["t1_distance_pct"] is not None
                    else None
                ),
                "t1_status": t1.get("status"),
                "t1_sessions_to_hit": t1.get("sessions_to_hit"),
                "t1_elapsed_hours_to_hit": t1.get("elapsed_hours_to_hit"),
            }
        )

    ranked.sort(key=lambda row: row["similarity"], reverse=True)
    selected = ranked[: max(1, min(int(top_k), 50))]
    sample = len(selected)
    hits = [row for row in selected if row.get("t1_status") == "HIT"]
    hit_rate = len(hits) / sample if sample else None
    sessions = [
        float(row["t1_sessions_to_hit"])
        for row in hits
        if row.get("t1_sessions_to_hit") is not None
    ]

    sufficient = sample >= minimum_sample
    return {
        "version": "SIMILAR_CASES_V1",
        "status": "READY" if sufficient else "INSUFFICIENT_SAMPLE",
        "sample": sample,
        "minimum_sample": minimum_sample,
        "descriptive_t1_hit_rate": round(hit_rate, 4) if sufficient and hit_rate is not None else None,
        "descriptive_t1_hit_rate_pct": round(hit_rate * 100.0, 1) if sufficient and hit_rate is not None else None,
        "median_t1_sessions_to_hit": round(float(median(sessions)), 2) if sufficient and sessions else None,
        "is_probability": False,
        "cases": selected if sufficient else selected[:5],
        "matching_features": current,
        "warning_ar": (
            "هذه نتائج وصفية لأقرب حالات ناضجة وليست احتمال نجاح مستقبلي. "
            "النسبة الاحتمالية لا تُعرض إلا من Target Calibration بعد اجتياز بوابات العينة."
        ),
    }
