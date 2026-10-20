"""Explosion model lab: pre-registered research models vs a baseline.

Every model is a fixed rule written before looking at results (nothing is
fitted), evaluated on daily OHLCV with signals known at the close of day t
and entry at the open of t+1. Outcome: within HOLD sessions, did price
reach the target before the stop? A bar that touches both is ambiguous and
scored as a loss (never a win). Net payoff subtracts a price-bucket cost.
The baseline is every eligible stock-day entered the same way, so a model
only shows an edge if it beats unconditional entries on the same data.

Models that need point-in-time data we do not have (historical catalysts,
premarket bars) are reported as NOT_TESTABLE instead of being approximated.
Research only; results never change live rules.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

TARGET_PCT = 8.0
STOP_PCT = 5.0
HOLD = 5
MIN_PRICE = 1.0
MIN_DOLLAR_VOLUME = 500_000.0


def cost_pct(price: float) -> float:
    if not math.isfinite(price) or price <= 0 or price < 2:
        return 1.5
    return 0.6 if price < 10 else 0.2


def features(bars: pd.DataFrame, bench_close: pd.Series | None) -> pd.DataFrame:
    """Causal features from daily bars (Open/High/Low/Close/Volume)."""
    f = pd.DataFrame(index=bars.index)
    close, high, low, open_, vol = (bars[c] for c in ("Close", "High", "Low", "Open", "Volume"))
    f["close"], f["open"], f["high"], f["low"] = close, open_, high, low
    f["prior_high20"] = high.shift(1).rolling(20).max()
    f["avg_vol20"] = vol.shift(1).rolling(20).mean()
    f["vol_ratio"] = vol / f["avg_vol20"]
    dollar = close * vol
    f["dollar_volume"] = dollar
    f["dollar_ratio"] = dollar / dollar.shift(1).rolling(20).mean()
    f["gap_pct"] = (open_ / close.shift(1) - 1) * 100
    rng = (high - low).replace(0, np.nan)
    f["close_location"] = (close - low) / rng
    f["sma50"] = close.rolling(50).mean()
    ret20 = close / close.shift(20) - 1
    if bench_close is not None:
        bench = bench_close.reindex(bars.index).ffill()
        f["rs20"] = (ret20 - (bench / bench.shift(20) - 1)) * 100
    else:
        f["rs20"] = np.nan
    f["eligible"] = (close >= MIN_PRICE) & (dollar.shift(1).rolling(20).mean() >= MIN_DOLLAR_VOLUME)
    return f


# Each model returns (signal mask, side) where side is "long" or "short".
MODELS: dict[str, Callable[[pd.DataFrame], tuple[pd.Series, str]]] = {
    "BREAKOUT_VOLUME": lambda f: ((f["close"] > f["prior_high20"]) & (f["vol_ratio"] >= 2.0), "long"),
    "RELATIVE_STRENGTH": lambda f: ((f["rs20"] >= 20) & (f["close"] > f["sma50"]), "long"),
    "LIQUIDITY_EXPANSION": lambda f: ((f["dollar_ratio"] >= 3.0) & (f["close_location"] >= 0.75), "long"),
    "GAP_CONTINUATION": lambda f: ((f["gap_pct"] >= 5.0) & (f["close"] > f["open"]), "long"),
    "FAILED_BREAKOUT_REVERSAL": lambda f: ((f["high"] > f["prior_high20"]) & (f["close"] < f["prior_high20"])
                                          & (f["close"] < f["open"]), "short"),
}
NOT_TESTABLE = {
    "CATALYST_FLOAT": "no point-in-time catalyst history (SEC access blocked; news archive not reconstructable)",
    "PREMARKET_MOMENTUM": "no historical premarket bars from an allowed source; a daily gap is not premarket momentum",
}


def _outcome(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
             i: int, side: str) -> tuple[float, str] | None:
    if i + 1 + HOLD > len(o):
        return None
    entry = float(o[i + 1])
    if not math.isfinite(entry) or entry <= 0:
        return None
    up, down = (entry * (1 + TARGET_PCT / 100), entry * (1 - STOP_PCT / 100)) if side == "long" else \
               (entry * (1 - TARGET_PCT / 100), entry * (1 + STOP_PCT / 100))
    payoff, status = None, "TIMEOUT"
    for j in range(i + 1, i + 1 + HOLD):
        hit_target = h[j] >= up if side == "long" else l[j] <= up
        hit_stop = l[j] <= down if side == "long" else h[j] >= down
        if hit_target and hit_stop:
            payoff, status = -STOP_PCT, "AMBIGUOUS_AS_LOSS"
            break
        if hit_stop:
            payoff, status = -STOP_PCT, "STOP"
            break
        if hit_target:
            payoff, status = TARGET_PCT, "TARGET"
            break
    if payoff is None:
        move = (float(c[i + HOLD]) / entry - 1) * 100
        payoff = move if side == "long" else -move
    return payoff - cost_pct(entry), status


def outcome(bars: pd.DataFrame, i: int, side: str) -> tuple[float, str] | None:
    """Enter at the open of i+1; return (net payoff %, status) or None if not enough bars."""
    return _outcome(*(bars[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close")), i, side)


def collect(universe: dict[str, pd.DataFrame], bench_close: pd.Series | None) -> pd.DataFrame:
    """One row per (symbol, date, model) signal plus baseline rows."""
    rows: list[dict[str, Any]] = []
    for symbol, bars in universe.items():
        if bars is None or len(bars) < 80:
            continue
        bars = bars.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        f = features(bars, bench_close)
        arrays = [bars[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close")]
        eligible = f["eligible"].fillna(False).to_numpy(dtype=bool)
        masks = {name: (mask.fillna(False).to_numpy(dtype=bool), side)
                 for name, (mask, side) in ((n, fn(f)) for n, fn in MODELS.items())}
        for i in range(60, len(bars) - HOLD - 1):
            if not eligible[i]:
                continue
            date = bars.index[i]
            base = _outcome(*arrays, i, "long")
            if base:
                rows.append({"symbol": symbol, "date": date, "model": "BASELINE_ALL_DAYS",
                             "net": base[0], "status": base[1]})
            for name, (mask, side) in masks.items():
                if mask[i]:
                    res = _outcome(*arrays, i, side)
                    if res:
                        rows.append({"symbol": symbol, "date": date, "model": name,
                                     "net": res[0], "status": res[1]})
    return pd.DataFrame(rows)


def _wilson_low(k: int, n: int, z: float = 1.96) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(centre - half, 4)


def summarize(group: pd.DataFrame) -> dict[str, Any]:
    n = len(group)
    wins = int((group["status"] == "TARGET").sum())
    return {
        "signals": n,
        "symbols": int(group["symbol"].nunique()) if n else 0,
        "target_hit_rate": round(wins / n, 4) if n else None,
        "target_hit_rate_ci_low": _wilson_low(wins, n),
        "breakeven_hit_rate": round(STOP_PCT / (TARGET_PCT + STOP_PCT), 4),
        "mean_net_pct": round(float(group["net"].mean()), 3) if n else None,
        "median_net_pct": round(float(group["net"].median()), 3) if n else None,
        "ambiguous_counted_as_loss": int((group["status"] == "AMBIGUOUS_AS_LOSS").sum()),
    }


def spa_vs_baseline(frame: pd.DataFrame, models: list[str], reps: int = 1000, seed: int = 7) -> dict[str, Any]:
    """Hansen SPA (arch) on daily mean net returns: does any model beat
    entering every eligible stock that day? Days without a model signal
    score 0 for that model (no position)."""
    try:
        from arch.bootstrap import SPA
    except ImportError:
        return {"status": "ARCH_UNAVAILABLE"}
    base = frame[frame["model"] == "BASELINE_ALL_DAYS"].groupby("date")["net"].mean()
    if len(base) < 60:
        return {"status": "INSUFFICIENT_DAYS", "days": len(base)}
    losses = {}
    for name in models:
        daily = frame[frame["model"] == name].groupby("date")["net"].mean().reindex(base.index).fillna(0.0)
        losses[name] = -daily.values
    spa = SPA(-base.values, pd.DataFrame(losses, index=base.index), reps=reps, block_size=10, seed=seed)
    spa.compute()
    p = spa.pvalues
    return {"status": "OK", "days": len(base), "reps": reps,
            "pvalue_consistent": round(float(p["consistent"]), 4),
            "pvalue_lower": round(float(p["lower"]), 4), "pvalue_upper": round(float(p["upper"]), 4),
            "null": "no model beats the all-days baseline", "library": "arch (NCSA) Hansen SPA"}


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"status": "NO_DATA"}
    dates = sorted(frame["date"].unique())
    cut = dates[len(dates) // 2]
    out: dict[str, Any] = {"models": {}, "split_date": str(pd.Timestamp(cut).date())}
    base_early = summarize(frame[(frame["model"] == "BASELINE_ALL_DAYS") & (frame["date"] < cut)])
    base_late = summarize(frame[(frame["model"] == "BASELINE_ALL_DAYS") & (frame["date"] >= cut)])
    for name in ["BASELINE_ALL_DAYS", *MODELS]:
        g = frame[frame["model"] == name]
        early, late = summarize(g[g["date"] < cut]), summarize(g[g["date"] >= cut])
        beats = (name != "BASELINE_ALL_DAYS" and early["signals"] >= 30 and late["signals"] >= 30
                 and early["mean_net_pct"] > base_early["mean_net_pct"]
                 and late["mean_net_pct"] > base_late["mean_net_pct"]
                 and late["mean_net_pct"] > 0)
        out["models"][name] = {"all": summarize(g), "early": early, "late": late,
                               "beats_baseline_both_halves_and_positive_late": bool(beats)}
    for name, reason in NOT_TESTABLE.items():
        out["models"][name] = {"status": "NOT_TESTABLE", "reason": reason}
    out["spa"] = spa_vs_baseline(frame, list(MODELS))
    return out
