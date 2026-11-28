"""Breakout-confirmation study: how early, how often right, and how much it pays (research only).

Owner questions (2026-11-28): a 1H close reached T1 ~82 % of decided cases yet the mean R was not
positive - why? And which confirmation balances speed, reward and risk across 3/5/10/15/30/60-minute
frames, a retest, relative volume and price structure? Nothing here changes a live rule.

Data per session (no look-ahead): levels from the prior completed session only (CALL trigger =
prior-day high, PUT trigger = prior-day low); ATR14 from completed sessions; regular-session 1-minute
bars, aggregated into completed session-aligned buckets. A rule fires on the close of the bar that
completes it; the outcome uses only 1-minute bars that START at or after that close.

Entry rules (at most one per side per session):
  C{m}   close of a completed m-minute bar beyond the trigger, m in 3,5,10,15,30,60
  R{m}   after such a close, the first later m-bar that comes back to the trigger (within 0.10 ATR)
         and still closes beyond it (retest held); entry at that close
  V{m}   C{m} whose bar volume is >= 1.5 x the same-window volume averaged over prior sessions
  H1F    1H close vs EMA20 of completed 1H bars agrees, then a 15m close beyond the trigger, then
         the next 5m bar trading beyond that 15m bar's extreme (entry at the extreme)
Stop models:
  map    the report's invalidation (trigger -/+ 0.25 x ATR14), whatever the entry
  bar    the extreme of the confirming bar (structure stop), if it lies on the right side
Target: the first ladder target (premarket_map) still beyond the entry; else none (close exit).
Outcome: T1 first, stop first, both inside one 1-minute bar (AMBIGUOUS, scored 0, never a win), or
the session close. R = move / |entry - stop|, minus 2 bp slippage per side; expectancy is also
given in ATR units so the two stop models can be compared.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

from options_radar import daily_plan as dp
from options_radar import premarket_map as pm

FRAMES = (3, 5, 10, 15, 30, 60)
RETEST_FRAMES = (5, 15)
RVOL_FRAMES = (5, 15)
RVOL_MIN = 1.5
RETEST_ATR = 0.10
SLIPPAGE = 0.0002
STOPS = ("map", "bar")
# Target models (2026-11-28 follow-up): T1 = first ladder target beyond the entry (live report),
# T2 = second, R1 = reward equal to risk, EOD = no target, exit at the session close (raw direction).
TARGET_RULES = ("C5", "V5", "C15", "C30", "C60", "H1F")
TARGETS = ("T1", "T2", "R1", "EOD")


@dataclass
class Signal:
    rule: str
    stop_model: str
    target_model: str
    side: str
    minutes_after_open: int
    preconf_atr: float      # how far beyond the trigger the entry already was (ATR units)
    outcome: str
    r: float
    r_atr: float            # the same result in ATR units
    mfe_r: float
    mae_r: float
    atr_pct: float          # ATR14 / prior close: volatility of the name
    stopped_within_30m: bool
    session: str = ""       # session date, for day-level bootstrap (signals within a day are correlated)
    delay_min: int = 0      # minutes between the rule completing and the entry (data + processing delay)


def bucket(bars: list[dict[str, Any]], open_at: datetime, minutes: int, step: int = 1) -> list[dict[str, Any]]:
    """Completed session-aligned buckets of `minutes` from `step`-minute bars ('t' = bar start)."""
    groups: dict[int, list[dict[str, Any]]] = {}
    for b in bars:
        idx = int((b["t"] - open_at).total_seconds() // (minutes * 60))
        if idx >= 0:
            groups.setdefault(idx, []).append(b)
    out = []
    need = minutes // step
    for idx in sorted(groups):
        rows = groups[idx]
        if len(rows) != need:
            continue  # a missing bar or the session end: not a completed bar
        out.append({"t": open_at + timedelta(minutes=idx * minutes), "end": open_at + timedelta(minutes=(idx + 1) * minutes),
                    "idx": idx, "o": rows[0]["o"], "h": max(r["h"] for r in rows), "l": min(r["l"] for r in rows),
                    "c": rows[-1]["c"], "v": sum(r.get("v", 0) for r in rows)})
    return out


def _beyond(price: float, trigger: float, side: str) -> bool:
    return price > trigger if side == "CALL" else price < trigger


def _score(after: list[dict[str, Any]], side: str, entry: float, stop: float, target: float | None,
           close_price: float, at: datetime) -> tuple[str, float, float, float, bool]:
    """(outcome, R, MFE R, MAE R, stopped within 30 minutes) from bars starting at/after `at`."""
    sign = 1 if side == "CALL" else -1
    risk = abs(entry - stop)
    cost = 2 * SLIPPAGE * entry / risk
    best = worst = 0.0
    for b in after:
        if b["t"] < at:
            raise ValueError("look-ahead: a bar that started before the entry was scored")
        best = max(best, (b["h"] - entry) if sign > 0 else (entry - b["l"]))
        worst = max(worst, (entry - b["l"]) if sign > 0 else (b["h"] - entry))
        hit_stop = b["l"] <= stop if sign > 0 else b["h"] >= stop
        hit_t1 = target is not None and (b["h"] >= target if sign > 0 else b["l"] <= target)
        if hit_stop and hit_t1:
            return "AMBIGUOUS", 0.0, best / risk, worst / risk, False
        if hit_stop:
            return "STOP", -1.0 - cost, best / risk, worst / risk, (b["t"] - at) < timedelta(minutes=30)
        if hit_t1:
            return "T1", (target - entry) * sign / risk - cost, best / risk, worst / risk, False
    return "CLOSE", sign * (close_price - entry) / risk - cost, best / risk, worst / risk, False


def session_signals(bars_1m: list[dict[str, Any]], open_at: datetime, prior: dict[str, float], atr14: float,
                    week: dict[str, float] | None, prior_hours: list[dict[str, Any]],
                    volume_baseline: dict[tuple[int, int], float] | None = None,
                    entry_delay_min: int = 0, rules: set[str] | None = None) -> list[Signal]:
    """Every rule x stop-model signal for one session. `volume_baseline[(m, idx)]` = mean prior volume."""
    pdh, pdl = prior["high"], prior["low"]
    rng = pdh - pdl
    if not bars_1m or rng <= 0 or atr14 <= 0:
        return []
    close_price = bars_1m[-1]["c"]
    atr_pct = atr14 / prior["close"] if prior.get("close") else 0.0
    frames = {m: bucket(bars_1m, open_at, m) for m in FRAMES}
    sides = {"CALL": (pdh, pdh - pm.INVALIDATION_ATR * atr14,
                      [t["value"] for t in pm._targets(pdh, 1, rng, atr14, (week or {}).get("high"))]),
             "PUT": (pdl, pdl + pm.INVALIDATION_ATR * atr14,
                     [t["value"] for t in pm._targets(pdl, -1, rng, atr14, (week or {}).get("low"))])}
    out: list[Signal] = []

    def emit(rule: str, side: str, entry: float, at: datetime, bar_stop: float) -> None:
        if rules is not None and rule not in rules:
            return
        trigger, map_stop, targets = sides[side]
        sign = 1 if side == "CALL" else -1
        if entry_delay_min:
            # the alert reaches the trader `entry_delay_min` later: enter at the close of that later minute
            late = next((b for b in bars_1m if b["t"] >= at + timedelta(minutes=entry_delay_min - 1)), None)
            if late is None:
                return
            entry, at = late["c"], late["t"] + timedelta(minutes=1)
        ahead = [t for t in targets if sign * (t - entry) > 0]
        after = [b for b in bars_1m if b["t"] >= at]
        for model, stop in (("map", map_stop), ("bar", bar_stop)):
            if sign * (entry - stop) <= 0:
                continue  # stop already behind the entry: no defined risk
            risk = abs(entry - stop)
            choices = {"T1": ahead[0] if ahead else None}
            if rule in TARGET_RULES:
                choices.update(T2=ahead[1] if len(ahead) > 1 else None, R1=entry + sign * risk, EOD=None)
            for tmodel, target in choices.items():
                outcome, r, mfe, mae, early_stop = _score(after, side, entry, stop, target, close_price, at)
                out.append(Signal(rule, model, tmodel, side, int((at - open_at).total_seconds() // 60),
                                  round(sign * (entry - trigger) / atr14, 4), outcome, r,
                                  r * risk / atr14, mfe, mae, atr_pct, early_stop,
                                  open_at.date().isoformat(), entry_delay_min))

    for side, (trigger, _, _) in sides.items():
        for m in FRAMES:
            first = next((b for b in frames[m] if _beyond(b["c"], trigger, side)), None)
            if first is None:
                continue
            extreme = first["l"] if side == "CALL" else first["h"]
            emit(f"C{m}", side, first["c"], first["end"], extreme)
            if m in RVOL_FRAMES and volume_baseline:
                base = volume_baseline.get((m, first["idx"]))
                if base and first["v"] >= RVOL_MIN * base:
                    emit(f"V{m}", side, first["c"], first["end"], extreme)
            if m in RETEST_FRAMES:
                for bar in (b for b in frames[m] if b["t"] >= first["end"]):
                    touched = (bar["l"] <= trigger + RETEST_ATR * atr14) if side == "CALL" else \
                              (bar["h"] >= trigger - RETEST_ATR * atr14)
                    if not _beyond(bar["c"], trigger, side):
                        break  # closed back inside: the breakout failed before any retest held
                    if touched:
                        emit(f"R{m}", side, bar["c"], bar["end"], bar["l"] if side == "CALL" else bar["h"])
                        break
        # H1F: hour trend agrees, 15m confirms, next 5m activates
        first15 = next((b for b in frames[15] if _beyond(b["c"], trigger, side)), None)
        if first15 is None:
            continue
        closes = [h["c"] for h in (*prior_hours, *frames[60]) if h["end"] <= first15["end"]]
        if len(closes) < 22 or not _beyond(closes[-1], dp.ema(closes, 20)[-1], side):
            continue
        level = first15["h"] if side == "CALL" else first15["l"]
        nxt = next((b for b in frames[5] if b["t"] >= first15["end"] and
                    ((b["h"] > level) if side == "CALL" else (b["l"] < level))), None)
        if nxt is not None:
            emit("H1F", side, level, nxt["end"], first15["l"] if side == "CALL" else first15["h"])
    return out


def _stats(rows: list[Signal]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    wins = [s.r for s in rows if s.r > 0]
    losses = [s.r for s in rows if s.r < 0]
    gross_loss = -sum(losses)
    return {
        "n": len(rows),
        "t1": round(sum(s.outcome == "T1" for s in rows) / len(rows), 3),
        "stop": round(sum(s.outcome == "STOP" for s in rows) / len(rows), 3),
        "close": round(sum(s.outcome == "CLOSE" for s in rows) / len(rows), 3),
        "ambig": sum(s.outcome == "AMBIGUOUS" for s in rows),
        "win_rate": round(len(wins) / len(rows), 3),
        "avg_win_r": round(mean(wins), 3) if wins else None,
        "avg_loss_r": round(mean(losses), 3) if losses else None,
        "exp_r": round(mean(s.r for s in rows), 3),
        "exp_atr": round(mean(s.r_atr for s in rows), 3),
        "pf": round(sum(wins) / gross_loss, 2) if gross_loss else None,
        "entry_min": int(median(s.minutes_after_open for s in rows)),
        "preconf_atr": round(median(s.preconf_atr for s in rows), 3),
        "mfe_r": round(median(s.mfe_r for s in rows), 2),
        "mae_r": round(median(s.mae_r for s in rows), 2),
        "false_break_30m": round(sum(s.stopped_within_30m for s in rows) / len(rows), 3),
    }


def summarise(signals: list[Signal]) -> dict[str, Any]:
    """Aggregate statistics only (no prices, no symbols), per rule x stop model and by condition."""
    out: dict[str, Any] = {}
    keys = sorted({(s.rule, s.stop_model, s.target_model) for s in signals})
    atr_cuts = sorted(s.atr_pct for s in signals)
    lo = atr_cuts[len(atr_cuts) // 3] if atr_cuts else 0
    hi = atr_cuts[2 * len(atr_cuts) // 3] if atr_cuts else 0
    for rule, model, tmodel in keys:
        rows = [s for s in signals if s.rule == rule and s.stop_model == model and s.target_model == tmodel]
        entry = _stats(rows)
        entry["by_entry_time"] = {name: _stats([s for s in rows if cond(s.minutes_after_open)]).get("exp_atr")
                                  for name, cond in (("first_30m", lambda m: m <= 30),
                                                     ("30_90m", lambda m: 30 < m <= 90),
                                                     ("after_90m", lambda m: m > 90))}
        entry["by_volatility"] = {name: _stats([s for s in rows if cond(s.atr_pct)]).get("exp_atr")
                                  for name, cond in (("low", lambda a: a < lo), ("mid", lambda a: lo <= a < hi),
                                                     ("high", lambda a: a >= hi))}
        out[f"{rule}/{model}/{tmodel}"] = entry
    return out


def validation_stats(rows: list[Signal], *, sessions: int, resamples: int = 2000, seed: int = 7) -> dict[str, Any]:
    """Out-of-sample statistics: every trade counted (close exit), day-level bootstrap CI, drawdown in R."""
    import random

    if not rows:
        return {"n": 0, "coverage": 0.0}
    base = _stats(rows)
    by_day: dict[str, list[float]] = {}
    for s in rows:
        by_day.setdefault(s.session, []).append(s.r)
    days = sorted(by_day)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        pick = [by_day[days[rng.randrange(len(days))]] for _ in days]
        flat = [x for d in pick for x in d]
        means.append(sum(flat) / len(flat))
    means.sort()
    equity = peak = dd = 0.0
    for s in sorted(rows, key=lambda x: (x.session, x.minutes_after_open)):
        equity += s.r
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return {**{k: base[k] for k in ("n", "win_rate", "avg_win_r", "avg_loss_r", "exp_r", "pf", "mfe_r", "mae_r",
                                     "entry_min", "close", "false_break_30m")},
            "median_r": round(median(s.r for s in rows), 3), "days_with_signal": len(days),
            "coverage": round(len(days) / sessions, 3) if sessions else None,
            "ci95_exp_r": [round(means[int(0.025 * resamples)], 3), round(means[int(0.975 * resamples)], 3)],
            "max_drawdown_r": round(dd, 2), "cost_bp_per_side": SLIPPAGE * 1e4}
