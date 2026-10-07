from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_scholes_price(
    *,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    volatility: float,
    side: str,
) -> float | None:
    """Return a research Black-Scholes premium estimate.

    This is a scenario model, not a live quote or execution price.
    """
    side = str(side or "").lower()
    if side not in {"call", "put"}:
        return None
    if min(spot, strike, volatility) <= 0:
        return None
    years = max(float(years), 1.0 / (365.0 * 24.0))
    sqrt_t = math.sqrt(years)
    denominator = volatility * sqrt_t
    if denominator <= 0:
        return None
    d1 = (
        math.log(spot / strike)
        + (rate + 0.5 * volatility * volatility) * years
    ) / denominator
    d2 = d1 - volatility * sqrt_t
    discount = math.exp(-rate * years)
    if side == "call":
        value = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    else:
        value = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return max(0.0, float(value))


_HORIZON_DAYS = {
    "INTRADAY_1D": 0.5,
    "SHORT_1_3D": 2.0,
    "SWING_3_7D": 5.0,
    "POSITION_1_4W": 15.0,
}


def _target_rows(
    stock: dict[str, Any],
    opportunity: dict[str, Any] | None,
) -> list[tuple[str, float, str]]:
    opportunity = opportunity or {}
    target_map = (
        opportunity.get("target_map")
        if isinstance(opportunity.get("target_map"), dict)
        else {}
    )
    horizon = (
        opportunity.get("target_horizon")
        if isinstance(opportunity.get("target_horizon"), dict)
        else {}
    )
    horizon_by_target = {
        str(row.get("target") or "").upper(): str(
            row.get("horizon_bucket") or ""
        ).upper()
        for row in horizon.get("targets", [])
        if isinstance(row, dict)
    }

    output: list[tuple[str, float, str]] = []
    for label, stock_key in (
        ("T1", "target_1"),
        ("T2", "target_2"),
        ("T3", "target_3"),
    ):
        mapped = target_map.get(label.lower())
        value = (
            _number(mapped.get("price"))
            if isinstance(mapped, dict)
            else _number(stock.get(stock_key))
        )
        if value <= 0:
            value = _number(stock.get(stock_key))
        if value <= 0:
            continue
        bucket = horizon_by_target.get(label) or str(
            horizon.get("primary_horizon") or "UNKNOWN"
        ).upper()
        output.append((label, value, bucket))
    return output


def build_premium_target_scenarios(
    contract: dict[str, Any],
    stock: dict[str, Any],
    opportunity: dict[str, Any] | None = None,
    *,
    risk_free_rate: float = 0.043,
) -> dict[str, Any]:
    """Estimate premium ranges at underlying T1/T2/T3 under IV/time scenarios.

    The engine deliberately returns ranges. Option premium depends on path,
    volatility and elapsed time, so a single exact target would overstate
    precision.
    """
    side = str(
        contract.get("side")
        or contract.get("option_type")
        or ""
    ).lower()
    if side == "call":
        normalized_side = "call"
    elif side == "put":
        normalized_side = "put"
    else:
        return {
            "available": False,
            "method": "BLACK_SCHOLES_SCENARIO_V1",
            "reason": "missing_or_invalid_option_side",
            "research_only": True,
        }

    spot = _number(
        contract.get("underlying_price"),
        _number(stock.get("price")),
    )
    strike = _number(contract.get("strike"))
    iv = _number(contract.get("iv"))
    dte = _number(contract.get("dte"))
    bid = _number(contract.get("bid"))
    ask = _number(contract.get("ask"))
    mid = _number(contract.get("mid"))
    entry = ask if ask > 0 else mid if mid > 0 else bid

    missing: list[str] = []
    if spot <= 0:
        missing.append("underlying_price")
    if strike <= 0:
        missing.append("strike")
    if iv <= 0:
        missing.append("iv")
    if dte <= 0:
        missing.append("dte")
    if entry <= 0:
        missing.append("entry_premium")

    targets = _target_rows(stock, opportunity)
    if not targets:
        missing.append("underlying_targets")

    invalidation = _number(
        (
            opportunity.get("target_map", {}).get("invalidation", {}).get("price")
            if isinstance(opportunity, dict)
            and isinstance(opportunity.get("target_map"), dict)
            and isinstance(
                opportunity.get("target_map", {}).get("invalidation"),
                dict,
            )
            else 0.0
        ),
        _number(stock.get("invalidation"), _number(stock.get("stop"))),
    )

    if missing:
        return {
            "available": False,
            "method": "BLACK_SCHOLES_SCENARIO_V1",
            "reason": "missing:" + ",".join(missing),
            "research_only": True,
        }

    iv_scenarios = {
        "iv_down": max(0.05, iv * 0.85),
        "base": iv,
        "iv_up": iv * 1.15,
    }

    rows: dict[str, Any] = {}
    for label, target_spot, bucket in targets:
        hold_days = _HORIZON_DAYS.get(bucket, min(max(dte * 0.12, 1.0), 5.0))
        remaining_days = max(dte - hold_days, 0.25)
        estimates: dict[str, float] = {}
        for scenario, scenario_iv in iv_scenarios.items():
            value = black_scholes_price(
                spot=target_spot,
                strike=strike,
                years=remaining_days / 365.0,
                rate=risk_free_rate,
                volatility=scenario_iv,
                side=normalized_side,
            )
            if value is not None:
                estimates[scenario] = round(value, 4)
        values = list(estimates.values())
        if not values:
            continue
        base_value = estimates.get("base", sum(values) / len(values))
        rows[label.lower()] = {
            "underlying_price": round(target_spot, 4),
            "horizon_bucket": bucket,
            "assumed_elapsed_days": round(hold_days, 2),
            "remaining_dte": round(remaining_days, 2),
            "premium_low": round(min(values), 4),
            "premium_base": round(base_value, 4),
            "premium_high": round(max(values), 4),
            "return_low_pct": round((min(values) / entry - 1.0) * 100.0, 2),
            "return_base_pct": round((base_value / entry - 1.0) * 100.0, 2),
            "return_high_pct": round((max(values) / entry - 1.0) * 100.0, 2),
            "scenario_prices": estimates,
        }

    invalidation_estimate: dict[str, Any] | None = None
    if invalidation > 0:
        hold_days = min(1.0, max(dte * 0.05, 0.25))
        remaining_days = max(dte - hold_days, 0.25)
        estimates = {}
        for scenario, scenario_iv in iv_scenarios.items():
            value = black_scholes_price(
                spot=invalidation,
                strike=strike,
                years=remaining_days / 365.0,
                rate=risk_free_rate,
                volatility=scenario_iv,
                side=normalized_side,
            )
            if value is not None:
                estimates[scenario] = round(value, 4)
        if estimates:
            values = list(estimates.values())
            base_value = estimates.get("base", sum(values) / len(values))
            invalidation_estimate = {
                "underlying_price": round(invalidation, 4),
                "premium_low": round(min(values), 4),
                "premium_base": round(base_value, 4),
                "premium_high": round(max(values), 4),
                "return_base_pct": round((base_value / entry - 1.0) * 100.0, 2),
            }

    return {
        "available": bool(rows),
        "method": "BLACK_SCHOLES_SCENARIO_V1",
        "entry_premium_reference": round(entry, 4),
        "entry_method": "ask" if ask > 0 else "mid" if mid > 0 else "bid",
        "spot_reference": round(spot, 4),
        "strike": round(strike, 4),
        "side": normalized_side.upper(),
        "dte": round(dte, 2),
        "iv_reference": round(iv, 6),
        "iv_scenarios": {
            key: round(value, 6) for key, value in iv_scenarios.items()
        },
        "targets": rows,
        "invalidation": invalidation_estimate,
        "research_only": True,
        "is_guarantee": False,
        "assumptions": [
            "Black-Scholes scenario estimate, not a live executable quote.",
            "IV scenarios use -15% / base / +15% relative to current IV.",
            "Target timing uses the existing underlying horizon buckets.",
            "Path, dividends, early exercise, skew and liquidity can move realized premium outside this range.",
        ],
    }
