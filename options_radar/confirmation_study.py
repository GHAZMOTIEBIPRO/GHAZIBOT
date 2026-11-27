"""Historical comparison of breakout-confirmation timeframes (research only, no alerts).

Question (owner, 2026-11-28): does a completed 1H close beyond the prior-day high/low confirm too
late for day trading / 0DTE, and does "1H trend + 15m confirmation + 5m activation" do better?
No timeframe is adopted before this measurement.

Per session and symbol the levels come from the prior completed session only (no look-ahead):
CALL trigger = prior-day high, PUT trigger = prior-day low, invalidation = trigger -/+ 0.25 x ATR14,
T1 = the first premarket_map target (same ladder as the live report). Methods, each at most one
signal per side per session, entry on the close of the bar that completes the rule:
  H1     completed 1H bar (session-aligned) closes beyond the trigger           (current rule)
  M15    completed 15m bar closes beyond the trigger
  M5     completed 5m bar closes beyond the trigger
  H1F_M15_M5  1H trend filter (close vs EMA20 of completed 1H bars, same side) + a 15m close
         beyond the trigger, then the next 5m bar that trades beyond that 15m bar's extreme
         (entry at that extreme, the activation price)
Outcome on later 5m bars of the same session: T1 first, invalidation first, both inside one bar
(AMBIGUOUS, never counted as a win), or neither by the close (CLOSE, scored at the close).
R is measured in units of the entry-to-invalidation distance; a fixed slippage is charged on both
sides. Results are reported per method and per chronological half (stability, no fitted params).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from options_radar import daily_plan as dp
from options_radar import premarket_map as pm

METHODS = ("H1", "M15", "M5", "H1F_M15_M5")
SLIPPAGE = 0.0002  # 2 bp per side on the underlying


@dataclass
class Signal:
    method: str
    side: str
    entry: float
    entry_at: datetime
    minutes_after_open: int
    outcome: str
    r: float
    mfe_r: float


def bucket(bars: list[dict[str, Any]], open_at: datetime, minutes: int) -> list[dict[str, Any]]:
    """Completed session-aligned buckets of `minutes` from 5m bars (bars carry 't' = start)."""
    groups: dict[int, list[dict[str, Any]]] = {}
    for b in bars:
        idx = int((b["t"] - open_at).total_seconds() // (minutes * 60))
        if idx >= 0:
            groups.setdefault(idx, []).append(b)
    out = []
    need = minutes // 5
    for idx in sorted(groups):
        rows = groups[idx]
        if len(rows) != need:
            continue  # incomplete (missing 5m bar or session end): not a completed bar
        out.append({"t": open_at + timedelta(minutes=idx * minutes), "end": open_at + timedelta(minutes=(idx + 1) * minutes),
                    "o": rows[0]["o"], "h": max(r["h"] for r in rows), "l": min(r["l"] for r in rows), "c": rows[-1]["c"]})
    return out


def _outcome(bars_after: list[dict[str, Any]], side: str, entry: float, stop: float, target: float | None,
             close_price: float) -> tuple[str, float, float]:
    sign = 1 if side == "CALL" else -1
    risk = abs(entry - stop)
    best = 0.0
    for b in bars_after:
        fav = (b["h"] - entry) if sign > 0 else (entry - b["l"])
        best = max(best, fav)
        hit_stop = b["l"] <= stop if sign > 0 else b["h"] >= stop
        hit_t1 = target is not None and (b["h"] >= target if sign > 0 else b["l"] <= target)
        if hit_stop and hit_t1:
            return "AMBIGUOUS", 0.0, best / risk
        if hit_stop:
            return "STOP", -1.0 - 2 * SLIPPAGE * entry / risk, best / risk
        if hit_t1:
            return "T1", abs(target - entry) / risk - 2 * SLIPPAGE * entry / risk, best / risk
    return "CLOSE", sign * (close_price - entry) / risk - 2 * SLIPPAGE * entry / risk, best / risk


def session_signals(day_bars: list[dict[str, Any]], open_at: datetime, prior: dict[str, float], atr14: float,
                    week: dict[str, float] | None, prior_hours: list[dict[str, Any]]) -> list[Signal]:
    """All method signals for one session. `prior_hours`: completed 1H bars of earlier sessions (EMA warm-up)."""
    pdh, pdl = prior["high"], prior["low"]
    rng = pdh - pdl
    if not day_bars or rng <= 0 or atr14 <= 0:
        return []
    close_price = day_bars[-1]["c"]
    frames = {"H1": bucket(day_bars, open_at, 60), "M15": bucket(day_bars, open_at, 15), "M5": bucket(day_bars, open_at, 5)}
    sides = {"CALL": (pdh, pdh - pm.INVALIDATION_ATR * atr14,
                      (pm._targets(pdh, 1, rng, atr14, (week or {}).get("high")) or [{}])[0].get("value")),
             "PUT": (pdl, pdl + pm.INVALIDATION_ATR * atr14,
                     (pm._targets(pdl, -1, rng, atr14, (week or {}).get("low")) or [{}])[0].get("value"))}
    out: list[Signal] = []

    def emit(method: str, side: str, entry: float, at: datetime) -> None:
        _trigger, stop, target = sides[side]
        later = [b for b in day_bars if b["t"] >= at]
        outcome, r, mfe = _outcome(later, side, entry, stop, target, close_price)
        out.append(Signal(method, side, entry, at, int((at - open_at).total_seconds() // 60), outcome, r, mfe))

    for method in ("H1", "M15", "M5"):
        for side, (trigger, _, _) in sides.items():
            for bar in frames[method]:
                if (bar["c"] > trigger) if side == "CALL" else (bar["c"] < trigger):
                    emit(method, side, bar["c"], bar["end"])
                    break
    # 1H trend filter + 15m confirmation + 5m activation
    for side, (trigger, _, _) in sides.items():
        for bar in frames["M15"]:
            if not ((bar["c"] > trigger) if side == "CALL" else (bar["c"] < trigger)):
                continue
            hours = [h for h in (*prior_hours, *frames["H1"]) if h["end"] <= bar["end"]]
            closes = [h["c"] for h in hours]
            if len(closes) < 22:
                break
            ema20 = dp.ema(closes, 20)[-1]
            if not ((closes[-1] > ema20) if side == "CALL" else (closes[-1] < ema20)):
                break  # the hour trend disagrees at the first confirmation: no signal this session
            level = bar["h"] if side == "CALL" else bar["l"]
            for b5 in (b for b in day_bars if b["t"] >= bar["end"]):
                if (b5["h"] > level) if side == "CALL" else (b5["l"] < level):
                    emit("H1F_M15_M5", side, level, b5["t"] + timedelta(minutes=5))
                    break
            break
    return out


def summarise(signals: list[Signal]) -> dict[str, Any]:
    """Aggregate statistics only (counts, rates, R, minutes): no prices, no symbols."""
    out: dict[str, Any] = {}
    for method in METHODS:
        rows = [s for s in signals if s.method == method]
        if not rows:
            out[method] = {"signals": 0}
            continue
        decided = [s for s in rows if s.outcome in ("T1", "STOP")]
        out[method] = {
            "signals": len(rows),
            "t1_first": sum(1 for s in rows if s.outcome == "T1"),
            "stop_first": sum(1 for s in rows if s.outcome == "STOP"),
            "ambiguous_same_bar": sum(1 for s in rows if s.outcome == "AMBIGUOUS"),
            "neither_by_close": sum(1 for s in rows if s.outcome == "CLOSE"),
            "t1_rate_of_decided": round(sum(1 for s in decided if s.outcome == "T1") / len(decided), 3) if decided else None,
            "avg_r": round(sum(s.r for s in rows) / len(rows), 3),
            "median_mfe_r": round(median(s.mfe_r for s in rows), 2),
            "median_entry_minutes_after_open": int(median(s.minutes_after_open for s in rows)),
            "share_entered_by_10_30": round(sum(1 for s in rows if s.minutes_after_open <= 60) / len(rows), 3),
        }
    return out
