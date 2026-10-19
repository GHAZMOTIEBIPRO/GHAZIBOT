"""Testable CALL / PUT / WAIT research rules for SPX, NDX, SPY and QQQ.

Consumes one row of ``index_radar.json`` (completed bars only, see
``scripts/build_index_context.py``). Every rule outcome is published so the
decision can be replayed and audited. No probability, no execution
authority: Yahoo bars are unofficial and may be delayed.

Rules (CALL shown; PUT is the mirror image):
  R1_DAILY_NOT_AGAINST  daily bias is UP or MIXED (never DOWN)
  R2_INTRADAY_ALIGNED   1H and 15M bias are both UP
  R3_ANCHOR_SIDE        last finished close above VWAP (ETFs) or 1H EMA9
  R4_NOT_EXHAUSTED      15M RSI14 below 72
  R5_LEVEL_BREAK        close above previous completed session high
CALL requires R1-R4; R5 upgrades the grade from EARLY to CONFIRMED.
Stale or missing intraday bars always yield WAIT (DATA_STALE).
"""
from __future__ import annotations

import math
from typing import Any

RULES_VERSION = "INDEX_DIRECTION_RULES_V1"
DIRECTION_SYMBOLS = ("SPX", "NDX", "SPY", "QQQ")
RSI_CEILING = 72.0
RSI_FLOOR = 28.0


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _bias(row: dict, frame: str) -> str:
    block = row.get(frame) if isinstance(row.get(frame), dict) else {}
    return str(block.get("bias") or "UNAVAILABLE")


def _levels(row: dict, side: str) -> list[float]:
    levels = row.get("levels") if isinstance(row.get("levels"), dict) else {}
    out = []
    for key in ("last_completed_session", "previous_week", "previous_month"):
        block = levels.get(key) if isinstance(levels.get(key), dict) else {}
        value = _num(block.get(side))
        if value is not None:
            out.append(value)
    return out


def _wait(code: str, reason_ar: str, rules: dict | None = None) -> dict[str, Any]:
    return {
        "version": RULES_VERSION,
        "decision": "WAIT",
        "grade": None,
        "reason_code": code,
        "reason_ar": reason_ar,
        "rules": rules or {},
        "targets": None,
        "invalidation": None,
        "research_only": True,
        "execution_authority": False,
        "probability": None,
    }


def build_index_direction(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict) or not row.get("current_intraday_bar_confirmed"):
        return _wait("DATA_STALE", "شموع اليوم غير حديثة أو غير مكتملة؛ لا اتجاه.")
    close = _num(row.get("last_finished_intraday_close"))
    h1 = row.get("h1") if isinstance(row.get("h1"), dict) else {}
    m15 = row.get("m15") if isinstance(row.get("m15"), dict) else {}
    anchor = _num(row.get("vwap_today"))
    anchor_source = "VWAP"
    if anchor is None:
        anchor, anchor_source = _num(h1.get("ema_fast")), "EMA9_1H"
    atr = _num(h1.get("atr14")) or _num(m15.get("atr14"))
    rsi = m15.get("rsi14")
    rsi = float(rsi) if isinstance(rsi, (int, float)) and math.isfinite(rsi) else None
    if close is None or anchor is None or atr is None or rsi is None:
        return _wait("DATA_INCOMPLETE", "مدخلات السعر أو المرجع أو ATR أو RSI ناقصة؛ لا اتجاه.")

    daily, hour, quarter = _bias(row, "daily"), _bias(row, "h1"), _bias(row, "m15")
    highs, lows = _levels(row, "high"), _levels(row, "low")
    prior = row.get("levels", {}).get("last_completed_session", {}) if isinstance(row.get("levels"), dict) else {}
    prior_high, prior_low = _num(prior.get("high")), _num(prior.get("low"))

    call = {
        "R1_DAILY_NOT_AGAINST": daily in ("UP", "MIXED"),
        "R2_INTRADAY_ALIGNED": hour == "UP" and quarter == "UP",
        "R3_ANCHOR_SIDE": close > anchor,
        "R4_NOT_EXHAUSTED": rsi < RSI_CEILING,
        "R5_LEVEL_BREAK": prior_high is not None and close > prior_high,
    }
    put = {
        "R1_DAILY_NOT_AGAINST": daily in ("DOWN", "MIXED"),
        "R2_INTRADAY_ALIGNED": hour == "DOWN" and quarter == "DOWN",
        "R3_ANCHOR_SIDE": close < anchor,
        "R4_NOT_EXHAUSTED": rsi > RSI_FLOOR,
        "R5_LEVEL_BREAK": prior_low is not None and close < prior_low,
    }
    required = ("R1_DAILY_NOT_AGAINST", "R2_INTRADAY_ALIGNED", "R3_ANCHOR_SIDE", "R4_NOT_EXHAUSTED")
    rules = {"CALL": call, "PUT": put, "anchor_source": anchor_source}
    for side, hits in (("CALL", call), ("PUT", put)):
        if not all(hits[name] for name in required):
            continue
        grade = "CONFIRMED" if hits["R5_LEVEL_BREAK"] else "EARLY"
        if side == "CALL":
            ahead = sorted(x for x in highs if x > close)
            t1 = ahead[0] if ahead else close + 1.5 * atr
            t2 = ahead[1] if len(ahead) > 1 else t1 + 1.5 * atr
            stop = anchor - 0.25 * atr
            reason = "تتوافق 1H و15M صعودًا فوق المرجع دون تشبع، والاتجاه اليومي لا يعارض."
        else:
            ahead = sorted((x for x in lows if x < close), reverse=True)
            t1 = ahead[0] if ahead else close - 1.5 * atr
            t2 = ahead[1] if len(ahead) > 1 else t1 - 1.5 * atr
            stop = anchor + 0.25 * atr
            reason = "تتوافق 1H و15M هبوطًا تحت المرجع دون تشبع، والاتجاه اليومي لا يعارض."
        return {
            "version": RULES_VERSION,
            "decision": side,
            "grade": grade,
            "reason_code": f"{side}_{grade}",
            "reason_ar": reason,
            "rules": rules,
            "reference_close": round(close, 3),
            "anchor": round(anchor, 3),
            "targets": {"t1": round(t1, 3), "t2": round(t2, 3)},
            "invalidation": round(stop, 3),
            "research_only": True,
            "execution_authority": False,
            "probability": None,
        }
    return _wait("RULES_NOT_MET", "لم تكتمل شروط CALL أو PUT؛ الانتظار أفضل من الدخول.", rules)
