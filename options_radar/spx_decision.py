from __future__ import annotations

import math
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def build_spx_trade_map(payload: dict[str, Any]) -> dict[str, Any]:
    """Build an explainable SPX CALL/PUT/no-trade map from structural levels.

    This is a research map. Gamma inputs remain positioning proxies unless a
    verified licensed source says otherwise.
    """
    spot = _num(payload.get("spot"))
    vwap = _num(payload.get("vwap"))
    vix = max(0.0, _num(payload.get("vix")))
    flip = _num(payload.get("zero_gamma_flip"))
    call_wall = _num(payload.get("call_wall"))
    put_wall = _num(payload.get("put_wall"))
    or_high = _num(payload.get("opening_range_high"))
    or_low = _num(payload.get("opening_range_low"))
    age = _num(payload.get("age_minutes"), 999.0)

    if spot <= 0 or vwap <= 0 or age > 20:
        return {
            "version": "SPX_TRADE_MAP_V1",
            "state": "DATA_INSUFFICIENT",
            "call_above": None,
            "put_below": None,
            "no_trade_zone": None,
            "reason_ar": "بيانات SPX غير مكتملة أو متأخرة؛ لا تُنشأ مستويات دخول.",
            "research_only": True,
        }

    expected_move = spot * (vix / 100.0) / math.sqrt(252.0) if vix > 0 else spot * 0.006
    buffer_points = max(spot * 0.0006, expected_move * 0.08)

    upper_refs = [vwap + buffer_points]
    lower_refs = [vwap - buffer_points]
    if or_high > 0:
        upper_refs.append(or_high + buffer_points * 0.20)
    if or_low > 0:
        lower_refs.append(or_low - buffer_points * 0.20)

    # Use Gamma Flip as a trigger reference only when it is close enough to the
    # current trading area. A distant stale/structural flip must not create an
    # unusably wide no-trade zone.
    if flip > 0 and abs(flip - spot) <= expected_move * 1.5:
        if flip >= vwap:
            upper_refs.append(flip + buffer_points * 0.20)
        else:
            lower_refs.append(flip - buffer_points * 0.20)

    call_above = max(upper_refs)
    put_below = min(lower_refs)

    if spot > call_above:
        state = "CALL"
        reason = "السعر فوق حد التفعيل العلوي مع تجاوز منطقة الحياد الهيكلية."
    elif spot < put_below:
        state = "PUT"
        reason = "السعر تحت حد التفعيل السفلي مع كسر منطقة الحياد الهيكلية."
    else:
        state = "NO_TRADE"
        reason = "السعر داخل منطقة الحياد؛ الانتظار حتى خروج واضح فوق CALL أو تحت PUT."

    call_candidates = [x for x in (call_wall, call_above + expected_move) if x > call_above]
    put_candidates = [x for x in (put_wall, put_below - expected_move) if 0 < x < put_below]
    call_target = min(call_candidates) if call_candidates else call_above + expected_move
    put_target = max(put_candidates) if put_candidates else max(0.0, put_below - expected_move)

    regime = str(payload.get("gamma_regime") or "unknown")
    return {
        "version": "SPX_TRADE_MAP_V1",
        "state": state,
        "call_above": round(call_above, 2),
        "put_below": round(put_below, 2),
        "no_trade_zone": {
            "low": round(put_below, 2),
            "high": round(call_above, 2),
        },
        "call_target": round(call_target, 2),
        "put_target": round(put_target, 2),
        "expected_move_1d_proxy": round(expected_move, 2),
        "buffer_points": round(buffer_points, 2),
        "gamma_flip": flip or None,
        "call_wall": call_wall or None,
        "put_wall": put_wall or None,
        "opening_range_high": or_high or None,
        "opening_range_low": or_low or None,
        "gamma_regime": regime,
        "reason_ar": reason,
        "research_only": True,
        "gamma_is_verified_dealer_inventory": False,
    }
