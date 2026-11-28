"""Small-cap early-move stages from Alpaca IEX snapshots + IEX daily history (pure; no network).

Replaces the Nasdaq.com screener input that has been SOURCE_TERMS_BLOCKED since 2026-10-21; scoring still
goes through the existing options_radar.microcap_hunter.assess_microcap_candidate.

Coverage honesty: IEX is one venue (a few % of U.S. volume). Today's volume AND its baseline are both IEX,
so relative volume compares like with like; neither is consolidated (SIP) volume, and dollar volume is IEX
dollar volume. Time-of-day RVOL = today's IEX volume / (20-session mean IEX volume x elapsed fraction of
the session, floor 5 %) - an approximation stated as such.

Stages (first match wins; EXTENDED is never an "early" detection):
  EXTENDED        move >= 25 % or price >= 20d high + 3 ATR
  CONFIRMED_MOVE  price above the 20d high, RVOL >= 3, move 8-25 %
  BREAKOUT_WATCH  price within 3 % below the 20d high, RVOL >= 1.5
  EARLY_ACTIVITY  RVOL >= 2, move < 8 %
  COMPRESSION     20d range <= 60 % of the 60d range and RVOL < 1.5
Eligibility: price 1-20, IEX dollar volume today >= $150k, 20 completed sessions, not an ETF.
Levels: trigger = 20d high, T1/T2/T3 = trigger + 1/2/3 ATR14, invalidation = trigger - 1 ATR14.
"""
from __future__ import annotations

from itertools import pairwise
from typing import Any

from options_radar.microcap_hunter import assess_microcap_candidate

PRICE_MIN, PRICE_MAX = 1.0, 20.0
MIN_IEX_DOLLAR_VOLUME = 150_000
# CONFIRMED_MOVE is a price/volume state, never a confirmed opportunity: halts, dilution (SEC shelf/ATM/
# warrants) and float are not checked on this path, and missing risk data blocks any promotion (owner,
# PHASE 4). The label says "research watch" and every row carries the unchecked risks.
STAGE_AR = {"COMPRESSION": "انضغاط", "EARLY_ACTIVITY": "نشاط مبكر", "BREAKOUT_WATCH": "مراقبة اختراق",
            "CONFIRMED_MOVE": "حركة قوية — مراقبة بحثية (المخاطر غير مفحوصة)", "EXTENDED": "ممتد (متأخر)"}
UNCHECKED_RISKS = ("halt_resume", "dilution_sec", "float_shares")
ALERT_STAGES = ("EARLY_ACTIVITY", "BREAKOUT_WATCH", "CONFIRMED_MOVE")


def _atr(rows: list[dict[str, float]], n: int = 14) -> float | None:
    if len(rows) < n + 1:
        return None
    trs = [max(r["h"] - r["l"], abs(r["h"] - p["c"]), abs(r["l"] - p["c"])) for p, r in pairwise(rows)]
    return sum(trs[-n:]) / n


def evaluate(symbol: str, snapshot: dict[str, Any], history: list[dict[str, float]], elapsed_fraction: float,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """`history`: completed daily IEX bars (o,h,l,c,v), oldest first, excluding today."""
    base = {"symbol": symbol, "feed": "IEX (single venue, partial volume)", "probability": None}
    if len(history) < 20:
        return {**base, "eligible": False, "reason": "fewer than 20 completed sessions"}
    day = snapshot.get("dailyBar") or {}
    trade = snapshot.get("latestTrade") or {}
    price = trade.get("p") or day.get("c")
    prev_close = history[-1]["c"]
    if not price or not (PRICE_MIN <= price <= PRICE_MAX):
        return {**base, "eligible": False, "reason": "price outside 1-20"}
    volume = float(day.get("v") or 0)
    dollar = volume * float(day.get("vw") or price)
    if dollar < MIN_IEX_DOLLAR_VOLUME:
        return {**base, "eligible": False, "reason": "IEX dollar volume below threshold"}
    avg20 = sum(r["v"] for r in history[-20:]) / 20
    rvol = volume / (avg20 * max(elapsed_fraction, 0.05)) if avg20 else 0.0
    high20 = max(r["h"] for r in history[-20:])
    range20 = high20 - min(r["l"] for r in history[-20:])
    range60 = max(r["h"] for r in history[-60:]) - min(r["l"] for r in history[-60:])
    atr = _atr(history) or 0.0
    move = (price / prev_close - 1) * 100
    if move >= 25 or (atr and price >= high20 + 3 * atr):
        stage = "EXTENDED"
    elif price > high20 and rvol >= 3 and 8 <= move < 25:
        stage = "CONFIRMED_MOVE"
    elif high20 * 0.97 <= price <= high20 and rvol >= 1.5:
        stage = "BREAKOUT_WATCH"
    elif rvol >= 2 and move < 8:
        stage = "EARLY_ACTIVITY"
    elif range60 and range20 <= 0.6 * range60 and rvol < 1.5:
        stage = "COMPRESSION"
    else:
        stage = None
    row = {"symbol": symbol, "price": price, "rvol": rvol, "dollar_volume": dollar, "day_move_pct": move,
           **(extra or {})}
    scored = assess_microcap_candidate(row)
    levels = None
    if atr:
        levels = {"trigger": round(high20, 2), "invalidation": round(high20 - atr, 2), "atr14": round(atr, 4),
                  "targets": [round(high20 + k * atr, 2) for k in (1, 2, 3)],
                  "method": "trigger = 20-session high; targets +1/+2/+3 ATR14; invalidation trigger - 1 ATR14"}
    return {**base, "eligible": True, "stage": stage, "stage_ar": STAGE_AR.get(stage), "opportunity_confirmed": False,
            "unchecked_risks": list(UNCHECKED_RISKS), "price": round(price, 4),
            "price_time": trade.get("t"), "move_pct": round(move, 2), "rvol_time_adjusted": round(rvol, 2),
            "iex_dollar_volume": round(dollar), "high20": round(high20, 4), "levels": levels,
            "score": scored.score, "assessment": scored.stage, "risk_flags": list(scored.flags),
            "dilution_context": scored.dilution_context, "reverse_split_context": scored.reverse_split_context}


def forward_moves(detected_price: float, detected_at_minute: int, closes_by_minute: dict[int, float],
                  close_price: float | None) -> dict[str, float | None]:
    """% change after 5/15/30/60 minutes and at the close, from the first-detection price."""
    out: dict[str, float | None] = {}
    for m in (5, 15, 30, 60):
        p = closes_by_minute.get(detected_at_minute + m)
        out[f"{m}m"] = round((p / detected_price - 1) * 100, 2) if p else None
    out["close"] = round((close_price / detected_price - 1) * 100, 2) if close_price else None
    return out
