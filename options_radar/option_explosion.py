from __future__ import annotations

import math
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pct100(value: Any) -> float:
    number = _num(value)
    if abs(number) <= 1.0:
        number *= 100.0
    return max(0.0, min(100.0, number))


def _trade_profile(row: dict[str, Any], dte: float) -> str:
    materiality = _num(row.get("catalyst_materiality") or row.get("materiality"))
    if row.get("event_trade") is True or materiality >= 80:
        return "EVENT"
    if dte <= 10:
        return "PREMIUM_EXPLOSION"
    return "SWING"


def _surface_score(row: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Use volatility dynamics when available; missing optional fields stay neutral."""
    iv_accel = _num(row.get("iv_acceleration_score"), float("nan"))
    if not math.isfinite(iv_accel):
        raw = _num(row.get("iv_acceleration_pct"), float("nan"))
        if math.isfinite(raw):
            iv_accel = max(0.0, min(100.0, 50.0 + raw * 4.0))
        else:
            iv_accel = 50.0

    iv_rank = _pct100(row.get("iv_rank")) if row.get("iv_rank") is not None else 50.0
    iv_percentile = _pct100(row.get("iv_percentile")) if row.get("iv_percentile") is not None else 50.0

    skew = abs(_num(row.get("iv_skew")))
    skew_score = max(0.0, min(100.0, skew * (100.0 if skew <= 1.0 else 1.0)))

    term = _num(row.get("term_structure_slope"))
    term_score = max(0.0, min(100.0, 50.0 + term * (100.0 if abs(term) <= 1.0 else 1.0)))

    score = (
        iv_accel * 0.45
        + iv_rank * 0.15
        + iv_percentile * 0.15
        + skew_score * 0.15
        + term_score * 0.10
    )
    return max(0.0, min(100.0, score)), {
        "iv_acceleration": round(iv_accel, 1),
        "iv_rank": round(iv_rank, 1),
        "iv_percentile": round(iv_percentile, 1),
        "skew": round(skew_score, 1),
        "term_structure": round(term_score, 1),
    }


def score_option_explosion(row: dict[str, Any]) -> dict[str, Any]:
    """Rank premium-expansion potential without claiming a guaranteed explosion.

    V2 uses different factor weights for short-convexity, swing and event setups.
    Optional volatility-surface fields improve the score when present but are
    never fabricated when the free data path cannot supply them.
    """
    volume = max(0.0, _num(row.get("volume")))
    oi = max(0.0, _num(row.get("open_interest")))
    vol_oi = _num(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    spread = max(0.0, _num(row.get("spread_pct"), 1.0))
    flow = _num(row.get("flow_momentum_score"))
    repeat = min(5.0, _num(row.get("repeat_flow_hits")))
    velocity = max(
        _num(row.get("flow_notional_velocity_per_min")),
        _num(row.get("verified_premium_velocity_per_min")),
    )
    gamma = abs(_num(row.get("gamma")))
    delta = abs(_num(row.get("delta")))
    theta = abs(_num(row.get("theta")))
    iv = max(0.0, _num(row.get("iv")))
    dte = max(0.0, _num(row.get("dte")))
    strict = _num(row.get("strict_score") or row.get("score"))
    consensus = _num(row.get("side_consensus_score"))
    cluster = _num(row.get("strike_cluster_score"))
    profile = _trade_profile(row, dte)

    activity = min(100.0, vol_oi * 28.0 + math.log10(max(volume, 1.0)) * 12.0)
    acceleration = min(100.0, repeat * 14.0 + math.log10(max(velocity, 1.0)) * 12.0)
    convexity = min(
        100.0,
        gamma * 800.0 + max(0.0, 1.0 - abs(delta - 0.45) / 0.35) * 45.0,
    )
    liquidity = max(
        0.0,
        min(
            100.0,
            100.0 - spread * 300.0 + min(20.0, math.log10(max(oi, 1.0)) * 5.0),
        ),
    )
    thesis = min(100.0, strict * 0.55 + consensus * 0.25 + flow * 0.20)
    clustering = min(100.0, cluster)
    surface, surface_detail = _surface_score(row)

    theta_drag = theta / max(delta, 0.05)
    theta_efficiency = max(0.0, min(100.0, 100.0 - theta_drag * 450.0))

    weights = {
        "PREMIUM_EXPLOSION": {
            "activity": 0.18,
            "acceleration": 0.22,
            "convexity": 0.20,
            "liquidity": 0.11,
            "thesis": 0.13,
            "clustering": 0.08,
            "surface": 0.06,
            "theta_efficiency": 0.02,
        },
        "SWING": {
            "activity": 0.10,
            "acceleration": 0.10,
            "convexity": 0.10,
            "liquidity": 0.17,
            "thesis": 0.25,
            "clustering": 0.05,
            "surface": 0.13,
            "theta_efficiency": 0.10,
        },
        "EVENT": {
            "activity": 0.10,
            "acceleration": 0.10,
            "convexity": 0.12,
            "liquidity": 0.13,
            "thesis": 0.17,
            "clustering": 0.05,
            "surface": 0.28,
            "theta_efficiency": 0.05,
        },
    }[profile]

    components = {
        "activity": activity,
        "acceleration": acceleration,
        "convexity": convexity,
        "liquidity": liquidity,
        "thesis": thesis,
        "clustering": clustering,
        "surface": surface,
        "theta_efficiency": theta_efficiency,
    }

    theta_penalty = 0.0
    if dte <= 1:
        theta_penalty = 18.0
    elif dte <= 3:
        theta_penalty = 8.0

    iv_percentile = surface_detail["iv_percentile"]
    verified_prints = _num(row.get("verified_unusual_print_count"))
    iv_crush_penalty = 0.0
    if (iv >= 1.5 or iv_percentile >= 90.0) and verified_prints <= 0:
        iv_crush_penalty = 12.0 if profile == "EVENT" else 8.0

    score = sum(components[name] * weight for name, weight in weights.items())
    score -= theta_penalty + iv_crush_penalty
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

    max_spread = {
        "PREMIUM_EXPLOSION": 0.22,
        "SWING": 0.14,
        "EVENT": 0.18,
    }[profile]

    blockers: list[str] = []
    if spread > max_spread:
        blockers.append("wide_spread_for_profile")
    if volume < 20 and oi < 50:
        blockers.append("thin_contract")
    if vol_oi < 0.5:
        blockers.append("weak_relative_activity")

    return {
        "version": "OPTION_EXPLOSION_V2_ADAPTIVE",
        "profile": profile,
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
            "volatility_surface": round(surface, 1),
            "theta_efficiency": round(theta_efficiency, 1),
        },
        "surface_detail": surface_detail,
        "weights": weights,
        "dynamic_max_spread_pct": max_spread,
        "penalties": {"theta": theta_penalty, "iv_crush": iv_crush_penalty},
        "blockers": blockers,
        "research_only": True,
        "guaranteed_explosion": False,
    }
