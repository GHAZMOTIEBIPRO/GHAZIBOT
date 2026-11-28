"""Pre-open price map: one computed JSON per symbol, reused by the text and any chart.

Pure functions, no network. Input is a plan from options_radar.daily_plan (completed
regular sessions) plus, when the provider returned them, completed extended-hours
5-minute bars of today's pre-market. Output is a frozen, versioned map:

- reference price and its type/time (pre-market last completed 5m bar, else the prior
  session close) - never a live quote;
- CALL side: trigger = prior-day high, confirmation = a completed hourly close above it,
  invalidation = trigger - 0.25 x ATR14, targets T1/T2/T3 picked from measured candidates;
- PUT side: the mirror on the prior-day low;
- WAIT band: between the two triggers;
- state: CALL_WATCH / PUT_WATCH / WAIT / NO_DATA. A WATCH means the four intraday-relevant
  frames (daily, 1H, 15m, 5m) all point the same way (the rule of
  options_radar.telegram_market_digest.assess); it is a condition to watch, never an
  entry, and CONFIRMED is only possible after the open on post-trigger bars, which this
  module does not see.

Target candidates and their stated methods (each must lie beyond the trigger by at least
0.10 x ATR14 and be at least 0.15 x ATR14 from the previous chosen target):
  prior-week high/low; prior-day range extensions 127.2 % and 161.8 %; a measured move of
  one prior-day range; one ATR14 beyond the trigger. Fewer than three valid candidates
  means fewer targets, with the reason - nothing is filled in.

No probability, no position size, no execution authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from options_radar.telegram_ar import NEW_YORK, clock_ar, day_month_ar
from options_radar.telegram_market_digest import assess

SCHEMA = "ghazi.premarket_map.v1"
INVALIDATION_ATR = 0.25
MIN_BEYOND_ATR = 0.10
MIN_SPACING_ATR = 0.15
MAX_TARGETS = 3

METHOD_AR = {
    "prior_week_high": "قمة الأسبوع السابق",
    "prior_week_low": "قاع الأسبوع السابق",
    "ext_1272": "امتداد 127.2% لمدى الجلسة السابقة",
    "ext_1618": "امتداد 161.8% لمدى الجلسة السابقة",
    "measured_move": "حركة مقاسة بمدى الجلسة السابقة",
    "atr_1": "ATR14 واحد بعد المحفز",
}
REF_AR = {"PREMARKET_LAST_COMPLETED_5M": "آخر شمعة 5د مكتملة قبل الافتتاح",
          "PRIOR_SESSION_CLOSE": "إغلاق الجلسة السابقة"}
STATE_AR = {"CALL_WATCH": "مراقبة CALL", "PUT_WATCH": "مراقبة PUT", "WAIT": "انتظار", "NO_DATA": "لا بيانات"}


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0:
        return None
    return float(raw)


def _r(value: float) -> float:
    return round(value, 2)


def _targets(trigger: float, side: int, rng: float, atr14: float, week_level: float | None) -> list[dict[str, Any]]:
    """Up to three measured targets beyond `trigger` (side +1 above, -1 below)."""
    week_name = "prior_week_high" if side > 0 else "prior_week_low"
    candidates = [(week_name, week_level),
                  ("ext_1272", trigger + side * 0.272 * rng),
                  ("ext_1618", trigger + side * 0.618 * rng),
                  ("measured_move", trigger + side * 1.0 * rng),
                  ("atr_1", trigger + side * 1.0 * atr14)]
    beyond = sorted(((m, v) for m, v in candidates if v is not None and side * (v - trigger) >= MIN_BEYOND_ATR * atr14),
                    key=lambda mv: side * (mv[1] - trigger))
    chosen: list[dict[str, Any]] = []
    for method, value in beyond:
        if chosen and abs(value - chosen[-1]["value"]) < MIN_SPACING_ATR * atr14:
            continue
        chosen.append({"name": f"T{len(chosen) + 1}", "value": _r(value), "method": method,
                       "method_ar": METHOD_AR[method]})
        if len(chosen) == MAX_TARGETS:
            break
    return chosen


def premarket_reference(bars_5m: list[dict[str, Any]], *, session_open: datetime, prior_close_at: datetime,
                        usable_until: datetime) -> dict[str, Any] | None:
    """Last completed extended-hours 5m bar after the prior close and before today's open.

    `bars_5m` rows: {"t": aware start, "o","h","l","c","v"}. A bar counts only when it ended
    by `usable_until` (the provider's delay boundary). Returns None when there is none.
    """
    rows = [b for b in bars_5m or []
            if isinstance(b, dict) and isinstance(b.get("t"), datetime) and prior_close_at <= b["t"] < session_open
            and b["t"].timestamp() + 300 <= usable_until.timestamp() and _num(b.get("c")) is not None]
    if not rows:
        return None
    last = rows[-1]
    return {"price": _r(float(last["c"])), "bar_start": last["t"].isoformat(),
            "high": _r(max(float(b["h"]) for b in rows)), "low": _r(min(float(b["l"]) for b in rows)),
            "volume": float(sum(float(b.get("v") or 0) for b in rows)), "bars": len(rows)}


def support_resistance(recent: list[dict[str, Any]] | None, call_trigger: float, put_trigger: float,
                       lookback: int = 20) -> dict[str, Any]:
    """Range extremes of the last `lookback` completed sessions, kept only beyond the triggers."""
    rows = [r for r in (recent or [])[-lookback:] if _num(r.get("high")) and _num(r.get("low"))]
    out: dict[str, Any] = {}
    if len(rows) >= 5:
        high, low = max(r["high"] for r in rows), min(r["low"] for r in rows)
        if high > call_trigger:
            out["resistance"] = {"value": _r(high), "basis": f"{len(rows)}-session high", "basis_ar": f"قمة {len(rows)} جلسة"}
        if low < put_trigger:
            out["support"] = {"value": _r(low), "basis": f"{len(rows)}-session low", "basis_ar": f"قاع {len(rows)} جلسة"}
    return out


def build_map(card: dict[str, Any], plan: dict[str, Any], *, premarket: dict[str, Any] | None = None) -> dict[str, Any]:
    """One symbol's map from its analysis card and plan; NO_DATA with a reason when it cannot be built."""
    symbol = str(plan.get("symbol") or card.get("symbol") or "")
    base = {"schema": SCHEMA, "symbol": symbol, "probability": None, "execution_authority": False}
    if not plan.get("available") or not card.get("available"):
        return {**base, "state": "NO_DATA", "reason": plan.get("reason") or card.get("reason") or "no completed reading"}
    prior = plan.get("prior_session") or {}
    pdh, pdl, pdc = _num(prior.get("high")), _num(prior.get("low")), _num(prior.get("close"))
    atr14 = _num(plan.get("atr14"))
    if pdh is None or pdl is None or pdc is None or pdh <= pdl:
        return {**base, "state": "NO_DATA", "reason": "prior-session levels unavailable"}
    if atr14 is None:
        return {**base, "state": "NO_DATA", "reason": "ATR14 unavailable (fewer than 15 completed sessions)"}
    rng = pdh - pdl
    week = plan.get("prior_week") or {}
    quality = card.get("data_quality") or {}
    daily_q = quality.get("daily") or {}
    if daily_q.get("status") != "OK" or daily_q.get("issues"):
        # the levels themselves come from the daily bars: no map without clean daily bars
        return {**base, "state": "NO_DATA", "reason": "daily bar quality checks did not pass"}
    reading = assess(card)  # blocks WATCH on any 5m quality issue; daily levels stay valid
    bias, aligned = reading.get("bias"), reading.get("aligned_frames", 0)
    state = ("CALL_WATCH" if bias == "UP" and aligned == 4 else "PUT_WATCH" if bias == "DOWN" and aligned == 4
             else "WAIT")
    if premarket and _num(premarket.get("price")) is not None:
        start = datetime.fromisoformat(premarket["bar_start"])
        ref = {"price": premarket["price"], "type": "PREMARKET_LAST_COMPLETED_5M", "time": premarket["bar_start"],
               "time_ar": f"شمعة {clock_ar(start, NEW_YORK)} نيويورك", "gap_pct": _r((premarket["price"] / pdc - 1) * 100)}
    else:
        ref = {"price": _r(pdc), "type": "PRIOR_SESSION_CLOSE", "time": prior.get("date"),
               "time_ar": f"جلسة {day_month_ar(str(prior.get('date')))}", "gap_pct": None}
    ref["type_ar"] = REF_AR[ref["type"]]
    price = ref["price"]
    position = "ABOVE_CALL_TRIGGER" if price > pdh else "BELOW_PUT_TRIGGER" if price < pdl else "INSIDE_WAIT_BAND"
    frames = ((card.get("interpretation") or {}).get("frames") or {})
    body = {
        **base, "state": state, "state_ar": STATE_AR[state],
        "data_as_of": plan.get("last_closed_session"), "feed_scope": plan.get("provider_scope"),
        "reference": ref, "position": position,
        "prior_day": {"date": prior.get("date"), "high": _r(pdh), "low": _r(pdl), "close": _r(pdc)},
        "pivot": _r((pdh + pdl + pdc) / 3), "atr14": _r(atr14),
        "call": {"trigger": _r(pdh), "confirmation": "completed 1H close above the trigger",
                 "invalidation": _r(pdh - INVALIDATION_ATR * atr14),
                 "targets": _targets(pdh, 1, rng, atr14, _num(week.get("high")))},
        "put": {"trigger": _r(pdl), "confirmation": "completed 1H close below the trigger",
                "invalidation": _r(pdl + INVALIDATION_ATR * atr14),
                "targets": _targets(pdl, -1, rng, atr14, _num(week.get("low")))},
        "wait_band": {"low": _r(pdl), "high": _r(pdh)},
        "levels_sr": support_resistance(plan.get("recent_daily"), pdh, pdl),
        "frames": {k: (frames.get(k) or {}).get("trend") for k in ("weekly", "daily", "4h", "1h", "15m", "5m")},
        "aligned_frames": aligned, "horizon": "current session",
        "distance_atr": _r(min(abs(price - pdh), abs(price - pdl)) / atr14),
    }
    for side in ("call", "put"):
        if len(body[side]["targets"]) < MAX_TARGETS:
            body[side]["targets_note"] = "fewer than three measured candidates beyond the trigger"
    body["map_id"] = map_id(body)
    return body


def map_id(body: dict[str, Any]) -> str:
    """Content hash: a changed map is a new version, never an edit of the old one."""
    clean = {k: v for k, v in body.items() if k != "map_id"}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, default=str).encode()).hexdigest()[:12]


def rank_details(maps: dict[str, dict[str, Any]], *, pinned: tuple[str, ...], limit: int = 5) -> list[str]:
    """Pinned index funds that have a map, then up to `limit` WATCH names nearest their trigger."""
    head = [s for s in pinned if (maps.get(s) or {}).get("state") not in (None, "NO_DATA")]
    watches = sorted((m for s, m in maps.items() if s not in pinned and m.get("state") in ("CALL_WATCH", "PUT_WATCH")),
                     key=lambda m: (m.get("distance_atr", 99), m["symbol"]))
    return head + [m["symbol"] for m in watches[:limit]]
