"""Daily multi-timeframe plan from completed bars only.

Pure functions (no network). A provider supplies completed daily bars and,
when it has them, intraday bars; this module never fetches, never invents a
level and never fills a frame it has no bars for.

Frames and how they are built:
- Weekly: aggregated from completed XNYS daily sessions, grouped by ISO
  week; a week counts only when its last session has closed.
- Daily: completed regular sessions only (the current session is excluded
  until its close).
- 4H: the regular session split into 09:30-13:30 and 13:30-16:00 New York
  (two buckets per day), built from completed 1H bars; a bucket counts only
  when complete.
- 1H / 15m / 5m: only when the provider supplies completed bars.

Indicators are chosen not to double count: trend uses close vs EMA20/EMA50
(one vote per frame), ATR14 sizes buffers, structure uses swing highs/lows.
Scenarios are conditional statements anchored on measured levels (prior
day high/low/close, prior week high/low) with ATR-based invalidation; they
carry no probability. Data quality is reported separately from how much the
frames agree.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from itertools import pairwise
from typing import Any

SCHEMA = "ghazi.daily_plan.v1"
MIN_DAILY = 22          # EMA20 + one comparison
# Minimum completed bars before a frame's trend is computed (fast EMA + 2 for a
# slope); EMA50 needs 50, ATR14 needs 15. Below these the frame says why.
REQUIREMENTS = {"weekly": {"trend_bars": 12, "ema": "EMA10/EMA20 (weeks)", "slow_from": 20},
                "daily": {"trend_bars": 22, "ema": "EMA20/EMA50", "slow_from": 50, "atr14_from": 15},
                "4h": {"trend_bars": 22, "ema": "EMA20/EMA50", "slow_from": 50},
                "1h": {"trend_bars": 22, "ema": "EMA20/EMA50", "slow_from": 50},
                "15m": {"trend_bars": 22, "ema": "EMA20/EMA50", "slow_from": 50},
                "5m": {"trend_bars": 22, "ema": "EMA20/EMA50", "slow_from": 50}}
TREND_AR = {"UP": "صاعد", "DOWN": "هابط", "MIXED": "مختلط", "INSUFFICIENT": "بيانات غير كافية",
            "UNAVAILABLE": "غير متاح"}


def ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    k = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, bar in pairwise(bars):
        trs.append(max(bar["high"] - bar["low"], abs(bar["high"] - prev["close"]), abs(bar["low"] - prev["close"])))
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period  # Wilder smoothing
    return value


def valid_bar(bar: Any) -> bool:
    if not isinstance(bar, dict):
        return False
    nums = [bar.get(k) for k in ("open", "high", "low", "close")]
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0 for n in nums):
        return False
    o, h, low, c = nums
    return h >= max(o, c, low) and low <= min(o, c, h)


def completed_daily(bars: list[dict[str, Any]], *, last_closed_session: str) -> list[dict[str, Any]]:
    """Valid, de-duplicated daily bars up to the last closed session."""
    by_day = {}
    for bar in bars:
        if valid_bar(bar) and isinstance(bar.get("date"), str) and bar["date"] <= last_closed_session:
            by_day[bar["date"]] = bar
    return [by_day[d] for d in sorted(by_day)]


def weekly_from_daily(daily: list[dict[str, Any]], *, last_closed_week_end: str) -> list[dict[str, Any]]:
    """ISO-week aggregation; weeks ending after last_closed_week_end are excluded."""
    weeks: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for bar in daily:
        y, w, _ = date.fromisoformat(bar["date"]).isocalendar()
        weeks.setdefault((y, w), []).append(bar)
    out = []
    for key in sorted(weeks):
        rows = weeks[key]
        if rows[-1]["date"] > last_closed_week_end:
            continue
        out.append({"week": f"{key[0]}-W{key[1]:02d}", "start": rows[0]["date"], "end": rows[-1]["date"],
                    "open": rows[0]["open"], "close": rows[-1]["close"],
                    "high": max(r["high"] for r in rows), "low": min(r["low"] for r in rows),
                    "volume": sum(r.get("volume") or 0 for r in rows), "sessions": len(rows)})
    return out


def frame_trend(bars: list[dict[str, Any]], *, fast: int = 20, slow: int = 50) -> dict[str, Any]:
    closes = [b["close"] for b in bars]
    if len(closes) < fast + 2:
        return {"trend": "INSUFFICIENT", "bars": len(closes),
                "reason": f"needs {fast + 2} completed bars for EMA{fast} and its slope, has {len(closes)}"}
    f = ema(closes, fast)
    s = ema(closes, slow) if len(closes) >= slow else None
    last = closes[-1]
    rising = f[-1] > f[-2]
    if s is not None:
        trend = "UP" if last > f[-1] > s[-1] else "DOWN" if last < f[-1] < s[-1] else "MIXED"
    else:
        trend = "UP" if last > f[-1] and rising else "DOWN" if last < f[-1] and not rising else "MIXED"
    return {"trend": trend, "bars": len(closes), "close": last, "ema_fast": round(f[-1], 4),
            "ema_slow": round(s[-1], 4) if s is not None else None, "ema_fast_rising": rising,
            "basis": f"close vs EMA{fast}" + (f"/EMA{slow}" if s is not None else " and its slope")}


def structure(bars: list[dict[str, Any]], lookback: int = 10) -> str:
    """Higher highs and higher lows (or the reverse) over two halves of the lookback."""
    if len(bars) < lookback:
        return "INSUFFICIENT"
    recent, before = bars[-lookback // 2:], bars[-lookback:-lookback // 2]
    hh = max(b["high"] for b in recent) > max(b["high"] for b in before)
    hl = min(b["low"] for b in recent) > min(b["low"] for b in before)
    lh = max(b["high"] for b in recent) < max(b["high"] for b in before)
    ll = min(b["low"] for b in recent) < min(b["low"] for b in before)
    return "HIGHER_HIGHS_LOWS" if hh and hl else "LOWER_HIGHS_LOWS" if lh and ll else "RANGE"


def scenarios(prior_day: dict[str, Any], prior_week: dict[str, Any] | None, atr14: float | None) -> list[dict[str, Any]]:
    """Conditional statements on measured levels; no probability attached."""
    if atr14 is None:
        return []
    buf = round(0.25 * atr14, 4)
    up_target = prior_week["high"] if prior_week and prior_week["high"] > prior_day["high"] else None
    down_target = prior_week["low"] if prior_week and prior_week["low"] < prior_day["low"] else None
    return [
        {"kind": "BULLISH", "trigger": f"close of a completed hourly bar above prior-day high {prior_day['high']}",
         "trigger_level": prior_day["high"], "target": up_target,
         "target_basis": "prior-week high" if up_target else "none above (no measured level)",
         "invalidation": round(prior_day["high"] - buf, 4), "invalidation_basis": "prior-day high − 0.25×ATR14",
         "horizon": "current session"},
        {"kind": "BEARISH", "trigger": f"close of a completed hourly bar below prior-day low {prior_day['low']}",
         "trigger_level": prior_day["low"], "target": down_target,
         "target_basis": "prior-week low" if down_target else "none below (no measured level)",
         "invalidation": round(prior_day["low"] + buf, 4), "invalidation_basis": "prior-day low + 0.25×ATR14",
         "horizon": "current session"},
        {"kind": "RANGE", "trigger": f"price stays between {prior_day['low']} and {prior_day['high']}",
         "trigger_level": None, "target": None, "target_basis": "no breakout: no trade setup",
         "invalidation": None, "invalidation_basis": "either breakout above", "horizon": "current session"},
    ]


def plan_for_symbol(symbol: str, daily_bars: list[dict[str, Any]], *, last_closed_session: str,
                    last_closed_week_end: str, provider: dict[str, Any],
                    intraday: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    daily = completed_daily(daily_bars, last_closed_session=last_closed_session)
    frames: dict[str, Any] = {}
    if len(daily) < 2:
        return {"symbol": symbol, "available": False, "reason": "fewer than two completed daily sessions",
                "provider": provider.get("name")}
    if daily[-1]["date"] != last_closed_session:
        # old bars are not a plan for today; levels must come from the last closed session
        return {"symbol": symbol, "available": False, "provider": provider.get("name"),
                "reason": f"stale: last daily bar {daily[-1]['date']} is not the last closed session {last_closed_session}"}
    intraday = {name: bars for name, bars in (intraday or {}).items()
                if bars and str(bars[-1].get("end") or "")[:10] >= last_closed_session}
    weekly = weekly_from_daily(daily, last_closed_week_end=last_closed_week_end)
    frames["weekly"] = {**frame_trend(weekly, fast=10, slow=20), "structure": structure(weekly, 8),
                        "last_bar_end": weekly[-1]["end"] if weekly else None}
    frames["daily"] = {**frame_trend(daily), "structure": structure(daily), "last_bar_end": daily[-1]["date"]}
    for name in ("4h", "1h", "15m", "5m"):
        bars = (intraday or {}).get(name) or []
        frames[name] = ({**frame_trend(bars), "structure": structure(bars), "last_bar_end": bars[-1].get("end"),
                         "partial_bars": sum(1 for x in bars if x.get("partial"))}
                        if bars else
                        {"trend": "UNAVAILABLE", "reason": "provider supplies no completed bars for this frame"})
    prior_day = daily[-1]
    prior_week = weekly[-1] if weekly else None
    atr14 = atr(daily)
    previous = daily[-2]
    votes = [f["trend"] for f in frames.values() if f["trend"] in ("UP", "DOWN", "MIXED")]
    agree = max((votes.count("UP"), votes.count("DOWN")), default=0)
    return {
        "symbol": symbol, "available": True, "provider": provider.get("name"),
        "provider_scope": provider.get("scope"), "delay_note": provider.get("delay_note"),
        "last_closed_session": daily[-1]["date"],
        "prior_session": {"date": prior_day["date"], "open": prior_day["open"], "high": prior_day["high"],
                          "low": prior_day["low"], "close": prior_day["close"],
                          "change_pct": round((prior_day["close"] / previous["close"] - 1) * 100, 2),
                          "gap_pct": round((prior_day["open"] / previous["close"] - 1) * 100, 2),
                          "volume": prior_day.get("volume"), "volume_scope": provider.get("volume_scope")},
        "prior_week": ({k: prior_week[k] for k in ("week", "high", "low", "close")} if prior_week else None),
        "atr14": round(atr14, 4) if atr14 is not None else None,
        "frames": frames,
        "frames_available": [k for k, f in frames.items() if f["trend"] not in ("UNAVAILABLE", "INSUFFICIENT")],
        "agreement": {"frames_voting": len(votes), "largest_same_direction": agree,
                      "note": "frames agreeing is not a probability; data quality is reported separately"},
        "scenarios": scenarios(prior_day, prior_week, atr14),
        # every level names where it came from and the bar it was measured on
        "levels": [{"name": n, "value": v, "source": provider.get("name"), "bar": bar_id}
                   for n, v, bar_id in (("prior_day_high", prior_day["high"], prior_day["date"]),
                                        ("prior_day_low", prior_day["low"], prior_day["date"]),
                                        ("prior_day_close", prior_day["close"], prior_day["date"]),
                                        ("prior_week_high", prior_week["high"] if prior_week else None,
                                         prior_week["week"] if prior_week else None),
                                        ("prior_week_low", prior_week["low"] if prior_week else None,
                                         prior_week["week"] if prior_week else None))
                   if v is not None],
        "data_quality": {"daily_bars": len(daily), "weekly_bars": len(weekly),
                         "sufficient_for_ema50": len(daily) >= 50, "sufficient_for_atr14": atr14 is not None},
        "probability": None, "execution_authority": False,
    }


def session_sheet(clock: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Session facts from the XNYS calendar (no prices)."""
    return {"date": clock.get("session_date"), "is_session": clock.get("is_session"),
            "regular_open": clock.get("regular_open"), "regular_close": clock.get("regular_close"),
            "reason": clock.get("reason"), "checked_at": now.isoformat()}
