"""Gamma-by-strike research heatmap from the existing normalized gamma map.

Independent implementation; no GammaGrid/AGPL source code, provider calls,
dealer positioning claims, or authorization to redistribute vendor data.
"""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any, *, nonnegative: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        return None
    return number


def _empty(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "levels": [],
        "status": "DATA_UNAVAILABLE",
        "research_only": True,
        "execution_grade": False,
        "dealer_inventory_verified": False,
        "display_authorized": False,
    }


def build_gamma_heatmap_research(
    gamma_map: dict[str, Any] | None, *, maximum_levels: int = 24,
) -> dict[str, Any]:
    """Build bounded, non-executable heatmap from already computed strike exposures.

    Signed values use the existing model's convention call-positive / put-negative,
    NOT a measurement of dealer positioning. No gamma flip is recalculated or
    presented as verified. Only the strongest strikes are selected for display,
    then sorted by strike for charting. Does not fetch, store, or publish quotes.
    """
    if not isinstance(gamma_map, dict):
        return _empty("missing_gamma_map")
    spot = _number(gamma_map.get("spot"))
    if spot is None or spot <= 0:
        return _empty("missing_spot")
    original = gamma_map.get("by_strike")
    if not isinstance(original, (list, tuple)) or not 1 <= len(original) <= 2000:
        return _empty("missing_or_excessive_strikes")
    if not isinstance(maximum_levels, int) or not 1 <= maximum_levels <= 100:
        raise ValueError("maximum_levels must be in 1..100")

    unique: set[float] = set()
    parsed: list[dict[str, float]] = []
    for item in original:
        if not isinstance(item, dict):
            return _empty("malformed_strike_row")
        strike = _number(item.get("strike"))
        call = _number(item.get("call_gex_proxy"), nonnegative=True)
        put = _number(item.get("put_gex_proxy"), nonnegative=True)
        oi = _number(item.get("total_oi"), nonnegative=True)
        if (strike is None or strike <= 0 or strike in unique or call is None
                or put is None or oi is None):
            return _empty("invalid_or_duplicate_strike")
        unique.add(strike)
        parsed.append({
            "strike": strike,
            "call": call,
            "put": put,
            "gross": call + put,
            "signed": call - put,
            "oi": oi,
        })
    gross_total = sum(item["gross"] for item in parsed)
    maximum = max((item["gross"] for item in parsed), default=0.0)
    if not math.isfinite(gross_total) or gross_total <= 0 or maximum <= 0:
        return _empty("no_calculable_gamma")
    selected = sorted(
        sorted(parsed, key=lambda row: (-row["gross"], abs(row["strike"] - spot)))
        [:maximum_levels],
        key=lambda row: row["strike"],
    )
    call_wall = _number(gamma_map.get("call_wall"))
    put_wall = _number(gamma_map.get("put_wall"))
    levels = [
        {
            "strike": round(row["strike"], 4),
            "call_gex_proxy": round(row["call"], 2),
            "put_gex_proxy": round(row["put"], 2),
            "signed_gex_proxy": round(row["signed"], 2),
            "signed_intensity_pct": round(row["signed"] / maximum * 100, 2),
            "gross_share_pct": round(row["gross"] / gross_total * 100, 2),
            "total_oi": round(row["oi"], 2),
            "call_wall": row["strike"] == call_wall,
            "put_wall": row["strike"] == put_wall,
        }
        for row in selected
    ]
    coverage = _number(gamma_map.get("gamma_coverage_pct"))
    oi_coverage = _number(gamma_map.get("oi_coverage_pct"))
    return {
        "available": True,
        "status": "RESEARCH_ONLY",
        "symbol": str(gamma_map.get("symbol") or "").upper(),
        "spot": spot,
        "levels": levels,
        "strikes_seen": len(parsed),
        "levels_shown": len(levels),
        "gross_gex_proxy": round(gross_total, 2),
        "gamma_coverage_pct": coverage,
        "oi_coverage_pct": oi_coverage,
        "coverage_warning": coverage is None or oi_coverage is None
            or coverage < 80 or oi_coverage < 80,
        "input_data_tier": str(gamma_map.get("data_tier") or "unavailable"),
        "sign_assumption": "call_plus_put_minus_not_dealer_positioning",
        "open_interest_is_historical": True,
        "gamma_flip_model_confirmed": False,
        "research_only": True,
        "execution_grade": False,
        "dealer_inventory_verified": False,
        "display_authorized": False,
        "data_license_requires_separate_approval": True,
    }
