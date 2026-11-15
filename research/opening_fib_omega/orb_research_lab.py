"""GHAZIMOTIEB | Opening Fibonacci Ω: underlying-only, CSV-based research lab.

Six deterministic candidate models; three fixed level families; multiple opening
windows. NO bundled market dataset, NO brokerage keys, NO option-P&L estimates.
Input: licensed-for-your-own-use US-equity/ETF 5-minute OHLCV with *aware*
ISO8601 timestamps. Enforces full XNYS RTH candles incl. early closes, signal
only after a closed bar, next-bar-open entry, pessimistic OHLC stop-before-target,
nonzero hypothetical spread/slippage/fees and a locked out-of-sample partition.

This is a research harness, not a claim that any strategy works.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd

TZ = ZoneInfo("America/New_York")
MODELS = ("ORB", "Retest", "Fib Reversal", "False Break", "VWAP Confluence", "MTF Alignment")
LEVELS = ("fib", "equal", "placebo")
WINDOWS = (5, 10, 15, 30, 60)
START = 570
LAST_ENTRY = 705  # 11:45 America/New_York, predeclared


@dataclass(frozen=True)
class Trade:
    symbol: str
    date: str
    model: str
    levels: str
    window: int
    side: int
    signal_at_utc: str
    fill_at_utc: str
    net_r: float
    exit_cause: str


def load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
    if not required <= set(frame):
        raise ValueError(f"Missing columns: {sorted(required - set(frame))}")
    if not frame["timestamp"].astype(str).str.contains(r"(?:Z|[+-]\d{2}:\d{2})$", regex=True).all():
        raise ValueError("Every timestamp needs an explicit Z or UTC offset")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    if not frame["symbol"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}").all():
        raise ValueError("Invalid symbol in research CSV")
    for key in ("open", "high", "low", "close", "volume"):
        frame[key] = pd.to_numeric(frame[key], errors="raise")
        if not np.isfinite(frame[key].values).all():
            raise ValueError(f"Invalid {key}: nonfinite")
    if ((frame[["open", "high", "low", "close"]] <= 0).any().any()
            or (frame["volume"] < 0).any()
            or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
            or (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
            or (frame["high"] < frame["low"]).any()):
        raise ValueError("Invalid OHLCV relationships")
    if frame.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("Duplicate candle")
    return frame.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def prepare_sessions(raw: pd.DataFrame) -> tuple[list[tuple[str, str, pd.DataFrame]], dict[str, int]]:
    """Full contiguous SIP-like RTH candles; source provenance must be checked separately."""
    cal = xcals.get_calendar("XNYS")
    f = raw.copy()
    local = f["timestamp"].dt.tz_convert(TZ)
    f["session"] = local.dt.date.astype(str)
    sessions: list[tuple[str, str, pd.DataFrame]] = []
    exclusions: dict[str, int] = {}
    for (symbol, day), g in f.groupby(["symbol", "session"], sort=True):
        try:
            dt = pd.Timestamp(day)
            if not cal.is_session(dt):
                raise ValueError("NOT_SESSION")
            schedule = cal.schedule.loc[day]
            opening = pd.Timestamp(schedule["open"]).tz_convert("UTC")
            closing = pd.Timestamp(schedule["close"]).tz_convert("UTC")
        except (ValueError, KeyError, TypeError):
            exclusions["NOT_SESSION"] = exclusions.get("NOT_SESSION", 0) + 1
            continue
        h = g.loc[(g["timestamp"] >= opening) & (g["timestamp"] < closing)].sort_values("timestamp").copy()
        expected = pd.date_range(opening, closing - pd.Timedelta(minutes=5), freq="5min", tz="UTC")
        times = pd.DatetimeIndex(h["timestamp"])
        if not times.equals(expected):
            exclusions["MISSING_OR_NON_5M_BARS"] = exclusions.get("MISSING_OR_NON_5M_BARS", 0) + 1
            continue
        h["ny_minute"] = h["timestamp"].dt.tz_convert(TZ).dt.hour * 60 + h["timestamp"].dt.tz_convert(TZ).dt.minute
        h.reset_index(drop=True, inplace=True)
        sessions.append((str(symbol), day, h))
    return sessions, exclusions


def level_spec(symbol: str, day: str, scheme: str) -> tuple[float, tuple[float, float, float]]:
    if scheme == "fib":
        return 0.382, (0.272, 0.618, 1.0)
    if scheme == "equal":
        return 0.40, (0.25, 0.60, 1.0)
    if scheme == "placebo":
        # Fixed random placebo decided by symbol/day, never selected by a return.
        token = hashlib.sha256(f"GHAZI_FIXED_PLACEBO_V1:{symbol}:{day}".encode()).digest()
        fraction = 0.25 + int.from_bytes(token[:4], "big") / (2**32) * 0.40
        return fraction, (0.20, 0.55, 0.90)
    raise ValueError(scheme)


def trade_one(symbol: str, day: str, b: pd.DataFrame, *, window: int, model: str,
              levels: str, cost_bps: float, min_rr: float = 1.5,
              daily_trend: int = 0) -> Trade | None:
    opening_n = window // 5
    if window not in WINDOWS or len(b) < opening_n + 3:
        return None
    op = b.iloc[:opening_n]
    hi = float(op["high"].max())
    lo = float(op["low"].min())
    width = hi - lo
    midpoint = 0.5 * (hi + lo)
    if width <= 0 or not 0.0012 <= width / midpoint <= 0.06:
        return None
    retrace, extensions = level_spec(symbol, day, levels)
    support, resist = lo + width * retrace, hi - width * retrace
    q = b.iloc[:].copy()
    typical = (q["high"] + q["low"] + q["close"]) / 3
    cvol = q["volume"].cumsum()
    vwap = (typical * q["volume"]).cumsum() / cvol.replace(0, np.nan)
    was_above = was_below = False
    for i in range(opening_n, len(q) - 1):
        row = q.iloc[i]
        minute = int(row["ny_minute"])
        if minute > LAST_ENTRY:
            break
        prev = q.iloc[i-1]
        close = float(row["close"])
        o = float(row["open"])
        l, h = float(row["low"]), float(row["high"])
        pclose = float(prev["close"])
        can_long = can_short = False
        if model in {"ORB", "VWAP Confluence", "MTF Alignment"}:
            can_long = close > hi and pclose > hi
            can_short = close < lo and pclose < lo
        elif model == "Retest":
            can_long = was_above and l <= hi + width * 0.2 and close > hi and close > o
            can_short = was_below and h >= lo - width * 0.2 and close < lo and close < o
        elif model == "Fib Reversal":
            can_long = l <= support and close > support and pclose <= support and close > o
            can_short = h >= resist and close < resist and pclose >= resist and close < o
        elif model == "False Break":
            can_long = float(prev["low"]) < lo and pclose > lo and close > float(prev["high"]) and close > o
            can_short = float(prev["high"]) > hi and pclose < hi and close < float(prev["low"]) and close < o
        if model == "VWAP Confluence":
            can_long &= np.isfinite(vwap.iloc[i]) and abs(vwap.iloc[i] - hi) <= 0.5 * width and close > vwap.iloc[i]
            can_short &= np.isfinite(vwap.iloc[i]) and abs(vwap.iloc[i] - lo) <= 0.5 * width and close < vwap.iloc[i]
        if model == "MTF Alignment":
            # Previous completed daily bias, fixed before today's open. A true
            # completed 60m-series test requires an independent, supplied feed.
            can_long &= daily_trend > 0
            can_short &= daily_trend < 0
            if i < 12:
                can_long = can_short = False
            else:
                prior_hour_mean = float(q.iloc[i-12:i]["close"].mean())
                can_long &= pclose > prior_hour_mean
                can_short &= pclose < prior_hour_mean
        was_above |= close > hi
        was_below |= close < lo
        if not (can_long or can_short):
            continue
        side = 1 if can_long else -1
        reversal = model in {"Fib Reversal", "False Break"}
        if model == "Fib Reversal":
            # Available at confirmation close, not an entire opening-range stop.
            # The v1 stop made 1.5R to the opposite opening boundary infeasible.
            stop = (min(l, float(prev["low"])) - 0.08 * width if side == 1 else
                    max(h, float(prev["high"])) + 0.08 * width)
        else:
            stop = (lo - 0.25 * width if side == 1 else hi + 0.25 * width) if reversal else (
                hi - 0.25 * width if side == 1 else lo + 0.25 * width)
        target1 = (midpoint if reversal else (hi + extensions[0] * width if side == 1 else lo - extensions[0] * width))
        target2 = ((hi if side == 1 else lo) if reversal else
                   (hi + extensions[1] * width if side == 1 else lo - extensions[1] * width))
        # The signal is known only at this bar's CLOSE, entry at next bar's OPEN.
        fillbar = q.iloc[i+1]
        entry = float(fillbar["open"])
        risk = side * (entry - stop)
        rr = side * (target2 - entry) / risk if risk > 0 else float("nan")
        if risk <= 0 or side * (target1 - entry) <= 0 or not np.isfinite(rr) or rr < min_rr:
            continue
        exit_price = float(q.iloc[-1]["close"])
        cause = "SESSION_END"
        for j in range(i + 1, len(q)):
            candle = q.iloc[j]
            bad = float(candle["low"]) <= stop if side == 1 else float(candle["high"]) >= stop
            good = float(candle["high"]) >= target2 if side == 1 else float(candle["low"]) <= target2
            # Conservative if both stops and targets touched in the same candle.
            if bad:
                opened_at = float(candle["open"])
                # A gap through a protective stop fills at the WORSE open,
                # never at an unavailable ideal stop price.
                exit_price = min(stop, opened_at) if side == 1 else max(stop, opened_at)
                cause = "STOP"
                break
            if good:
                exit_price, cause = target2, "TARGET2"
                break
        cost = entry * cost_bps / 10000.0
        r = (side * (exit_price - entry) - cost) / risk
        return Trade(symbol, day, model, levels, window, side,
                     (pd.Timestamp(row["timestamp"]) + pd.Timedelta(minutes=5)).isoformat(),
                     pd.Timestamp(fillbar["timestamp"]).isoformat(),
                     round(float(r), 6), cause)
    return None


def describe(trades: list[Trade]) -> dict[str, Any]:
    r = np.asarray([t.net_r for t in trades], dtype=float)
    if len(r) == 0:
        return {"trades": 0, "proven_edge": False, "status": "NO_TRADES"}
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    streak = longest = 0
    for v in r:
        streak = streak + 1 if v < 0 else 0
        longest = max(streak, longest)
    return {"trades": len(r), "mean_net_r": round(float(r.mean()), 5),
            "win_rate_percent": round(float((r > 0).mean() * 100), 2),
            "profit_factor": round(float(gains/losses), 3) if losses > 0 else None,
            "consecutive_losses": longest,
            "statuses": {status: sum(t.exit_cause == status for t in trades)
                         for status in ("STOP", "TARGET2", "SESSION_END")},
            "proven_edge": False,
            "status": "DESCRIPTIVE_ONLY" if len(r) >= 30 else "INSUFFICIENT_SAMPLE"}


def blocked_bootstrap(trades: list[Trade], *, draws: int = 1000, seed: int = 71413) -> dict[str, Any]:
    """Resample *days*, preserving same-day overlapping symbols as clusters.

    This estimates dispersion of underlying-price proxy R values; it does NOT
    estimate live option profitability or solve selection-overfit by itself.
    """
    by_day: dict[str, list[float]] = {}
    for row in trades:
        by_day.setdefault(row.date, []).append(row.net_r)
    if len(trades) < 30 or len(by_day) < 15:
        return {"status": "INSUFFICIENT_DAILY_CLUSTERS", "trades": len(trades),
                "distinct_days": len(by_day)}
    rng = np.random.default_rng(seed)
    values = list(by_day.values())
    means: list[float] = []
    drawdowns: list[float] = []
    for _ in range(draws):
        sampled = rng.integers(0, len(values), size=len(values))
        series = np.asarray([r for idx in sampled for r in values[int(idx)]], dtype=float)
        means.append(float(series.mean()))
        # 0.5% capital risk per *sequential* trade is a thought experiment,
        # not a portfolio backtest with overlapping simultaneous positions.
        wealth = np.cumprod(1 + np.clip(series * 0.005, -0.99, None))
        highwater = np.maximum.accumulate(np.r_[1., wealth])
        drawdowns.append(float(np.max(1 - wealth / highwater[1:])))
    return {"status": "DESCRIPTIVE_BOOTSTRAP_ONLY",
            "daily_block_mean_r_95pct": [round(float(x), 5) for x in np.quantile(means, [.025, .975])],
            "hypothetical_serial_max_drawdown_p95_pct": round(float(np.quantile(drawdowns, .95) * 100), 3),
            "draws": draws, "proven_edge": False}


def walk_forward_validate(sessions: list[tuple[str, str, pd.DataFrame]], *,
                          costs_bps: float) -> dict[str, Any]:
    """Expanding train + following test folds, wholly within first 75% of days.

    Final 25% is untouched. Each fold chooses on training data ONLY, then
    observes an immediately subsequent chronological validation window.
    """
    days = sorted({day for _, day, _ in sessions})
    if len(days) < 120:
        return {"status": "INSUFFICIENT_SESSIONS_FOR_WALK_FORWARD", "sessions": len(days)}
    development = days[:int(len(days) * .75)]
    train_days = max(30, int(len(development) * .48))
    fold_days = max(10, int(len(development) * .15))
    folds = []
    history: dict[str, list[float]] = {}
    trend: dict[tuple[str, str], int] = {}
    for symbol, day, bars in sorted(sessions, key=lambda x: (x[1], x[0])):
        x = history.setdefault(symbol, [])
        bias = 0
        if len(x) >= 20:
            ema = float(pd.Series(x).ewm(span=20, adjust=False).mean().iloc[-1])
            bias = 1 if x[-1] > ema else (-1 if x[-1] < ema else 0)
        trend[(symbol, day)] = bias
        x.append(float(bars.iloc[-1]["close"]))
    for j in range(3):
        boundary = train_days + j * fold_days
        testing_days = set(development[boundary:boundary+fold_days])
        training_days = set(development[:boundary])
        if len(testing_days) < 5:
            break
        choices = []
        for window in WINDOWS:
            for model in MODELS:
                for scheme in LEVELS:
                    train_trades: list[Trade] = []
                    for sym, day, bars in sessions:
                        if day not in training_days:
                            continue
                        t = trade_one(sym, day, bars, window=window, model=model,
                                      levels=scheme, cost_bps=costs_bps,
                                      daily_trend=trend[(sym, day)])
                        if t:
                            train_trades.append(t)
                    if len(train_trades) >= 30:
                        choices.append((float(np.mean([x.net_r for x in train_trades])),
                                        window, model, scheme))
        if not choices:
            folds.append({"fold": j + 1, "status": "NO_TRAIN_CANDIDATE_WITH_30_TRADES"})
            continue
        _, window, model, scheme = max(choices)
        held: list[Trade] = []
        for sym, day, bars in sessions:
            if day not in testing_days:
                continue
            t = trade_one(sym, day, bars, window=window, model=model,
                          levels=scheme, cost_bps=costs_bps,
                          daily_trend=trend[(sym, day)])
            if t:
                held.append(t)
        folds.append({"fold": j + 1, "training_end": max(training_days),
                      "validation_start": min(testing_days),
                      "validation_end": max(testing_days),
                      "chosen": f"{window}:{model}:{scheme}",
                      "validation": describe(held),
                      "bootstrap": blocked_bootstrap(held)})
    return {"status": "WALK_FORWARD_DESCRIPTIVE_NOT_PROVEN", "folds": folds,
            "final_25pct_holdout_touched": False}


def train_validation_test(sessions: list[tuple[str, str, pd.DataFrame]], *,
                          costs_bps: float, universe: tuple[str, ...] = ()) -> dict[str, Any]:
    days = sorted({day for _, day, _ in sessions})
    # Split by SESSION DAY across symbols so prices from the same session cannot
    # leak into both training and OOS. The last 25% is a sealed final holdout.
    if len(days) < 80:
        return {"status": "INSUFFICIENT_SESSIONS_FOR_OOS", "sessions": len(days),
                "minimum_required": 80, "proven_edge": False}
    k1, k2 = int(len(days) * 0.5), int(len(days) * 0.75)
    partitions = {"train": set(days[:k1]), "validation": set(days[k1:k2]),
                  "holdout": set(days[k2:])}
    development_days = partitions["train"] | partitions["validation"]
    session_trend: dict[tuple[str, str], int] = {}
    prior_by_symbol: dict[str, list[float]] = {}
    for symbol, day, b in sorted(sessions, key=lambda x: (x[1], x[0])):
        hist = prior_by_symbol.setdefault(symbol, [])
        trend = 0
        if len(hist) >= 20:
            ema20 = float(pd.Series(hist).ewm(span=20, adjust=False).mean().iloc[-1])
            trend = 1 if hist[-1] > ema20 else (-1 if hist[-1] < ema20 else 0)
        session_trend[(symbol, day)] = trend
        hist.append(float(b.iloc[-1]["close"]))
    grid = {}
    # This is a finite, predefined research grid, not a performance-selected
    # adaptive random-search loop. No parameters are optimized against holdout.
    for win in WINDOWS:
        for model in MODELS:
            for levels in LEVELS:
                key = f"{win}:{model}:{levels}"
                trades = []
                for symbol, day, b in sessions:
                    # Never inspect future held-out outcomes in the grid search.
                    if day not in development_days or (universe and symbol not in universe):
                        continue
                    tx = trade_one(symbol, day, b, window=win, model=model,
                                   levels=levels, cost_bps=costs_bps,
                                   daily_trend=session_trend[(symbol, day)])
                    if tx:
                        trades.append(tx)
                trades.sort(key=lambda t: (t.date, t.fill_at_utc, t.symbol))
                grid[key] = {p: describe([x for x in trades if x.date in selected])
                             for p, selected in partitions.items() if p != "holdout"}
    # Select ONLY on train, subject to sufficient samples. Evaluate validation
    # without retuning. Holdout stays sealed until explicit acceptance protocol.
    ranked = [(k, v["train"]["mean_net_r"])
              for k, v in grid.items()
              if v["train"].get("trades", 0) >= 30 and
                 v["train"].get("mean_net_r") is not None]
    ranked.sort(key=lambda x: x[1], reverse=True)
    candidate = ranked[0][0] if ranked else None
    return {"schema": "ghazi.quantum_orb_lab.v1", "status": "RESEARCH_NOT_PROVEN",
            "source_sessions": len(days), "source_symbol_sessions": len(sessions),
            "costs_roundtrip_bps_assumed": costs_bps, "partition_days": {
                k: {"from": min(v), "to": max(v), "count": len(v)} for k, v in partitions.items()},
            "candidate_selected_on_train_only": candidate,
            "candidate_validation": grid[candidate]["validation"] if candidate else None,
            "holdout_sealed": True,
            "grid_results_train_validation": {k: {"train": v["train"], "validation": v["validation"]}
                                              for k, v in grid.items()},
            "holdout_is_not_viewed_for_tuning": True,
            "proven_edge": False,
            "note": "Does not test option prices, fills, Greeks, or executable spreads."}


def main() -> None:
    p = argparse.ArgumentParser(description="Price-only, non-lookahead XNYS opening range research")
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cost-bps", type=float, default=12., help="roundtrip underlying costs, hypothetical basis points")
    p.add_argument("--symbols", nargs="*", default=[])
    args = p.parse_args()
    if not (0 < args.cost_bps < 500):
        p.error("Cost needs a positive finite plausible number in bps")
    raw = load_csv(args.csv)
    sessions, excluded = prepare_sessions(raw)
    result = train_validation_test(sessions, costs_bps=args.cost_bps,
                                   universe=tuple(x.upper() for x in args.symbols))
    result["excluded_symbol_sessions"] = excluded
    result["walk_forward"] = walk_forward_validate(sessions, costs_bps=args.cost_bps)
    result["source_csv_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    result["source_rights_must_be_verified_by_user"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Research status: {result['status']}; unique sessions: {len(set(day for _, day, _ in sessions))}; no options P&L")


if __name__ == "__main__":
    main()