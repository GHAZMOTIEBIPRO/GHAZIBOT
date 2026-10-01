from __future__ import annotations

import math
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def score_option_explosion(row: dict[str, Any]) -> dict[str, Any]:
    """Rank premium-expansion potential without claiming a guaranteed explosion."""
    volume = max(0.0, _num(row.get("volume")))
    oi = max(0.0, _num(row.get("open_interest")))
    vol_oi = _num(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    spread = max(0.0, _num(row.get("spread_pct"), 1.0))
    flow = _num(row.get("flow_momentum_score"))
    repeat = min(5.0, _num(row.get("repeat_flow_hits")))
    velocity = max(_num(row.get("flow_notional_velocity_per_min")), _num(row.get("verified_premium_velocity_per_min")))
    gamma = abs(_num(row.get("gamma")))
    delta = abs(_num(row.get("delta")))
    iv = max(0.0, _num(row.get("iv")))
    dte = max(0.0, _num(row.get("dte")))
    strict = _num(row.get("strict_score") or row.get("score"))
    consensus = _num(row.get("side_consensus_score"))
    cluster = _num(row.get("strike_cluster_score"))

    activity = min(100.0, vol_oi * 28.0 + math.log10(max(volume, 1.0)) * 12.0)
    acceleration = min(100.0, repeat * 14.0 + math.log10(max(velocity, 1.0)) * 12.0)
    convexity = min(100.0, gamma * 800.0 + max(0.0, 1.0 - abs(delta - 0.45) / 0.35) * 45.0)
    liquidity = max(0.0, min(100.0, 100.0 - spread * 300.0 + min(20.0, math.log10(max(oi, 1.0)) * 5.0)))
    thesis = min(100.0, strict * 0.55 + consensus * 0.25 + flow * 0.20)
    clustering = min(100.0, cluster)

    theta_penalty = 0.0
    if dte <= 1:
        theta_penalty = 18.0
    elif dte <= 3:
        theta_penalty = 8.0
    iv_crush_penalty = 10.0 if iv >= 1.5 and not row.get("verified_unusual_print_count") else 0.0

    score = (
        activity * 0.20
        + acceleration * 0.20
        + convexity * 0.16
        + liquidity * 0.14
        + thesis * 0.22
        + clustering * 0.08
        - theta_penalty
        - iv_crush_penalty
    )
    score = max(0.0, min(100.0, score))

    if dte <= 2:
        horizon = "INTRADAY_0_2D"
        time_ar = "نفس اليوم إلى يومين"
    elif dte <= 10:
        horizon = "WEEK_3_10D"
        time_ar = "3–10 أيام"
    else:
        horizon = "SWING_2_6W"
        time_ar = "أسبوعان إلى 6 أسابيع"

    blockers: list[str] = []
    if spread > 0.20:
        blockers.append("wide_spread")
    if volume < 20 and oi < 50:
        blockers.append("thin_contract")
    if vol_oi < 0.5:
        blockers.append("weak_relative_activity")

    return {
        "version": "OPTION_EXPLOSION_V1",
        "score": round(score, 1),
        "label": "HIGH" if score >= 82 else "BUILDING" if score >= 68 else "LOW",
        "horizon": horizon,
        "estimated_window_ar": time_ar,
        "components": {
            "activity": round(activity, 1),
            "acceleration": round(acceleration, 1),
            "convexity": round(convexity, 1),
            "liquidity": round(liquidity, 1),
            "thesis": round(thesis, 1),
            "strike_cluster": round(clustering, 1),
        },
        "penalties": {"theta": theta_penalty, "iv_crush": iv_crush_penalty},
        "blockers": blockers,
        "research_only": True,
        "guaranteed_explosion": False,
    }
