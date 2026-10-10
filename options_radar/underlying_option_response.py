from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _target_component(premium_targets: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    targets = (
        premium_targets.get("targets")
        if isinstance(premium_targets.get("targets"), dict)
        else {}
    )
    t1 = targets.get("t1") if isinstance(targets.get("t1"), dict) else {}
    t2 = targets.get("t2") if isinstance(targets.get("t2"), dict) else {}
    returns = [
        _number(t1.get("return_base_pct"), float("nan")),
        _number(t2.get("return_base_pct"), float("nan")),
    ]
    finite = [value for value in returns if math.isfinite(value)]
    if not finite:
        return 35.0, {"available": False, "reason": "missing_target_response"}

    primary = finite[0]
    secondary = finite[1] if len(finite) > 1 else primary
    score = _clamp(45.0 + 0.55 * primary + 0.20 * max(0.0, secondary))

    low = _number(t1.get("return_low_pct"), float("nan"))
    base = _number(t1.get("return_base_pct"), float("nan"))
    high = _number(t1.get("return_high_pct"), float("nan"))
    scenario_values = [value for value in (low, base, high) if math.isfinite(value)]
    positive_share = (
        sum(value > 0 for value in scenario_values) / len(scenario_values)
        if scenario_values
        else 0.0
    )
    score = _clamp(score * (0.75 + 0.25 * positive_share))
    return score, {
        "available": True,
        "t1_return_base_pct": round(primary, 2),
        "t2_return_base_pct": round(secondary, 2),
        "t1_positive_scenario_share": round(positive_share, 4),
    }


def _asymmetry_component(premium_targets: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    targets = (
        premium_targets.get("targets")
        if isinstance(premium_targets.get("targets"), dict)
        else {}
    )
    t1 = targets.get("t1") if isinstance(targets.get("t1"), dict) else {}
    invalidation = (
        premium_targets.get("invalidation")
        if isinstance(premium_targets.get("invalidation"), dict)
        else {}
    )
    gain = _number(t1.get("return_base_pct"), float("nan"))
    invalidation_return = _number(
        invalidation.get("return_base_pct"),
        float("nan"),
    )
    if not math.isfinite(gain) or not math.isfinite(invalidation_return):
        return 45.0, {"available": False, "reason": "missing_invalidation_scenario"}
    loss = abs(min(invalidation_return, -1e-6))
    reward_risk = max(0.0, gain) / loss
    score = _clamp(20.0 + min(reward_risk, 4.0) / 4.0 * 80.0)
    if gain <= 0:
        score = min(score, 25.0)
    return score, {
        "available": True,
        "reward_risk_to_t1": round(reward_risk, 4),
        "t1_return_base_pct": round(gain, 2),
        "invalidation_return_base_pct": round(invalidation_return, 2),
    }


def _responsiveness_component(contract: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    delta = abs(_number(contract.get("delta"), float("nan")))
    spot = _number(contract.get("underlying_price"))
    entry = _number(
        contract.get("ask"),
        _number(contract.get("mid"), _number(contract.get("bid"))),
    )
    if not math.isfinite(delta) or delta <= 0 or spot <= 0 or entry <= 0:
        return 35.0, {"available": False, "reason": "missing_delta_or_price"}

    elasticity = delta * spot / entry
    delta_balance = math.exp(-(((delta - 0.52) / 0.28) ** 2))
    elasticity_score = min(1.0, elasticity / 18.0)
    score = 100.0 * (0.58 * delta_balance + 0.42 * elasticity_score)
    return _clamp(score), {
        "available": True,
        "delta": round(delta, 4),
        "elasticity_proxy": round(elasticity, 4),
        "note": "delta*spot/premium is a local elasticity proxy, not a promised return",
    }


def _liquidity_component(contract: dict[str, Any]) -> tuple[float, bool, dict[str, Any]]:
    bid = _number(contract.get("bid"))
    ask = _number(contract.get("ask"))
    spread = _number(contract.get("spread_pct"), float("nan"))
    oi = max(0.0, _number(contract.get("open_interest")))
    volume = max(0.0, _number(contract.get("volume")))

    two_sided = bid > 0 and ask > bid
    if not math.isfinite(spread) and two_sided:
        spread = (ask - bid) / ((ask + bid) / 2.0)

    spread_score = (
        _clamp(100.0 * (1.0 - spread / 0.20))
        if math.isfinite(spread)
        else 0.0
    )
    oi_score = _clamp(math.log10(oi + 1.0) / math.log10(5001.0) * 100.0)
    volume_score = _clamp(
        math.log10(volume + 1.0) / math.log10(5001.0) * 100.0
    )
    score = 0.60 * spread_score + 0.25 * oi_score + 0.15 * volume_score
    hard_gate = (
        not two_sided
        or not math.isfinite(spread)
        or spread > 0.15
        or oi < 50
    )
    return _clamp(score), hard_gate, {
        "two_sided_quote": two_sided,
        "spread_pct": round(spread, 6) if math.isfinite(spread) else None,
        "open_interest": int(oi),
        "volume": int(volume),
        "hard_gate": hard_gate,
    }


def _decay_component(contract: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    theta = abs(_number(contract.get("theta"), float("nan")))
    entry = _number(
        contract.get("ask"),
        _number(contract.get("mid"), _number(contract.get("bid"))),
    )
    dte = _number(contract.get("dte"))
    if not math.isfinite(theta) or theta <= 0 or entry <= 0:
        return 50.0, {"available": False, "reason": "missing_theta_or_premium"}
    daily_drag = theta / entry
    score = _clamp(100.0 * (1.0 - daily_drag / 0.08))
    if dte <= 2:
        score *= 0.55
    elif dte <= 7:
        score *= 0.75
    return _clamp(score), {
        "available": True,
        "theta_to_premium_per_day": round(daily_drag, 6),
        "dte": round(dte, 2),
    }


def _volatility_component(contract: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    iv = _number(contract.get("iv"), float("nan"))
    hv = _number(contract.get("realized_volatility_30d"), float("nan"))
    iv_rank = _number(contract.get("iv_rank"), float("nan"))
    iv_percentile = _number(contract.get("iv_percentile"), float("nan"))

    value_parts: list[tuple[float, float]] = []
    iv_hv_ratio = None
    if math.isfinite(iv) and iv > 0 and math.isfinite(hv) and hv > 0:
        iv_hv_ratio = iv / hv
        # For a long-option buyer, IV below realized volatility is favorable.
        # This is a value heuristic, not a forecast that realized vol persists.
        ratio_score = _clamp(100.0 * (1.55 - iv_hv_ratio))
        value_parts.append((ratio_score, 0.60))

    rank_values: list[float] = []
    if math.isfinite(iv_rank):
        rank_values.append(_clamp(100.0 - iv_rank))
    if math.isfinite(iv_percentile):
        rank_values.append(_clamp(100.0 - iv_percentile))
    if rank_values:
        value_parts.append((sum(rank_values) / len(rank_values), 0.40))

    if not value_parts:
        return 50.0, {
            "available": False,
            "reason": "missing_realized_vol_and_iv_history",
        }

    weight_sum = sum(weight for _, weight in value_parts)
    score = sum(value * weight for value, weight in value_parts) / weight_sum
    return _clamp(score), {
        "available": True,
        "iv": round(iv, 6) if math.isfinite(iv) else None,
        "realized_volatility_30d": round(hv, 6) if math.isfinite(hv) else None,
        "iv_to_realized_vol_ratio": (
            round(iv_hv_ratio, 4) if iv_hv_ratio is not None else None
        ),
        "iv_rank": round(iv_rank, 2) if math.isfinite(iv_rank) else None,
        "iv_percentile": (
            round(iv_percentile, 2) if math.isfinite(iv_percentile) else None
        ),
        "note": "IV/HV is buyer-value context, not an empirical return probability",
    }


def grade_underlying_option_response(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Grade how well a long option maps to the underlying chart thesis.

    This is an independent GHAZIBOT implementation inspired by permissively
    licensed option-contract grading and chart-first contract-selection work.
    It never changes V11 or production alert authority.
    """

    premium_targets = (
        contract.get("premium_targets")
        if isinstance(contract.get("premium_targets"), dict)
        else {}
    )
    target_score, target_detail = _target_component(premium_targets)
    asymmetry_score, asymmetry_detail = _asymmetry_component(premium_targets)
    response_score, response_detail = _responsiveness_component(contract)
    liquidity_score, liquidity_gate, liquidity_detail = _liquidity_component(contract)
    decay_score, decay_detail = _decay_component(contract)
    volatility_score, volatility_detail = _volatility_component(contract)

    weights = {
        "target_response": 0.27,
        "target_invalidation_asymmetry": 0.20,
        "underlying_responsiveness": 0.18,
        "liquidity": 0.20,
        "time_decay": 0.08,
        "volatility_value": 0.07,
    }
    components = {
        "target_response": target_score,
        "target_invalidation_asymmetry": asymmetry_score,
        "underlying_responsiveness": response_score,
        "liquidity": liquidity_score,
        "time_decay": decay_score,
        "volatility_value": volatility_score,
    }
    weighted = sum(components[key] * weights[key] for key in weights)
    final_score = min(weighted, 39.0) if liquidity_gate else weighted

    return {
        "version": "UNDERLYING_OPTION_RESPONSE_V1",
        "score": round(_clamp(final_score), 2),
        "grade": _grade(final_score),
        "weighted_score_before_gate": round(_clamp(weighted), 2),
        "liquidity_hard_cap_applied": liquidity_gate,
        "components": {
            key: {
                "score": round(components[key], 2),
                "weight": weights[key],
            }
            for key in weights
        },
        "details": {
            "target_response": target_detail,
            "target_invalidation_asymmetry": asymmetry_detail,
            "underlying_responsiveness": response_detail,
            "liquidity": liquidity_detail,
            "time_decay": decay_detail,
            "volatility_value": volatility_detail,
        },
        "research_only": True,
        "decision_authority": False,
        "score_is_probability": False,
        "automatic_execution": False,
        "policy": {
            "underlying_thesis_first": True,
            "volume_oi_never_sets_direction": True,
            "wide_or_thin_quotes_fail_closed": True,
            "v11_unchanged": True,
        },
    }
