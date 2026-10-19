"""Research-only price-action confluence and point-in-time historical replay.

Uses completed daily candles and the existing MIT pandas-ta-classic adapter.
Neither price-pattern confluence nor news-search attention promotes trading
authority, validates an option contract, or proves a probability of profit.
"""
from __future__ import annotations

from importlib import import_module
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

LOOKBACK = 20
BAND_LOOKBACK = 40
MIN_HISTORY = 65
HORIZON_SESSIONS = 5
RVOL_TRIGGER = 1.5


def _base(reason: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "stage": "INSUFFICIENT_EVIDENCE",
        "research_only": True,
        "live_decision_authority": False,
        "options_execution_eligible": False,
        "source_family": "yahoo",
        "independent_price_confirmation": False,
        "official_catalyst_verified": False,
        "price_probability": None,
        "source_last_daily_bar": None,
        "rvol_daily": None,
        "prior_20_high": None,
        "prior_20_low": None,
        "breakout_close_above_prior_high": None,
        "volume_confirmation": None,
        "compression_within_prior_5_sessions": None,
        "breakout_after_compression": None,
        "historical_replay": {
            "version": 1,
            "lookahead_safe": True,
            "measurement": "forward five completed daily sessions after signal close",
            "matured_events": 0,
            "median_best_forward_5session_pct": None,
            "median_worst_forward_5session_pct": None,
            "win_probability": None,
            "outcomes_promoted": False,
        },
    }


def _valid(history: pd.DataFrame | None) -> bool:
    if history is None or not isinstance(history.index, pd.DatetimeIndex):
        return False
    if len(history) < MIN_HISTORY:
        return False
    if not history.index.is_monotonic_increasing or history.index.has_duplicates:
        return False
    required = ("Open", "High", "Low", "Close", "Volume")
    if not set(required).issubset(history.columns):
        return False
    try:
        values = history[list(required)].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(values).all():
        return False
    return bool(
        (values[:, :4] > 0).all() and (values[:, 4] >= 0).all()
        and (values[:, 1] >= np.maximum(values[:, 0], values[:, 3])).all()
        and (values[:, 2] <= np.minimum(values[:, 0], values[:, 3])).all()
        and (values[:, 1] >= values[:, 2]).all()
    )


def price_confluence_shadow(history: pd.DataFrame | None) -> dict[str, Any]:
    """A one-pass deterministic replay with no future data in signal formation."""
    if not _valid(history):
        return _base("INVALID_OR_INSUFFICIENT_DAILY_OHLCV")
    try:
        ta = import_module("pandas_ta_classic")
        bands = ta.bbands(history["Close"].astype(float), length=20, std=2, talib=False)
        names = [x for x in bands.columns if str(x).startswith("BBB_")]
        if len(names) != 1:
            return _base("BOLLINGER_BANDWIDTH_UNAVAILABLE")
        width = pd.to_numeric(bands[names[0]], errors="coerce").to_numpy(dtype=float)
    except (ImportError, ValueError, AttributeError, TypeError, IndexError):
        return _base("BOLLINGER_CALCULATION_UNAVAILABLE")

    frame = history.iloc[-130:]
    # Recompute aligned widths if rolling retention limited the observation set.
    widths = width[-len(frame):]
    close = frame["Close"].to_numpy(dtype=float)
    high = frame["High"].to_numpy(dtype=float)
    low = frame["Low"].to_numpy(dtype=float)
    volume = frame["Volume"].to_numpy(dtype=float)
    n = len(close)
    # Signal at i depends only on the bar ending at i and its past.
    signals: list[dict[str, Any] | None] = [None] * n
    for i in range(BAND_LOOKBACK + LOOKBACK, n):
        previous_widths = widths[i - BAND_LOOKBACK:i]
        threshold = np.percentile(previous_widths, 25)
        if not np.isfinite(previous_widths).all() or not np.isfinite(widths[i]) or threshold <= 0:
            continue
        compression_now = bool(widths[i] <= threshold)
        # A prior compressed candle is known at i; no future-pattern inference.
        prior_compression = False
        for past in range(max(BAND_LOOKBACK + LOOKBACK, i - 5), i):
            reference = widths[past - BAND_LOOKBACK:past]
            if np.isfinite(reference).all() and np.isfinite(widths[past]):
                prior_compression |= bool(widths[past] <= np.percentile(reference, 25))
        mean_volume = float(np.mean(volume[i - LOOKBACK:i]))
        rvol = float(volume[i] / mean_volume) if mean_volume > 0 else None
        resistance = float(np.max(high[i - LOOKBACK:i]))
        support = float(np.min(low[i - LOOKBACK:i]))
        breakout = bool(close[i] > resistance)
        volume_ok = bool(rvol is not None and rvol >= RVOL_TRIGGER)
        confirmed = breakout and volume_ok and prior_compression
        stage = (
            "BREAKOUT_AFTER_COMPRESSION" if confirmed
            else "VOLUME_BREAKOUT_WATCH" if breakout and volume_ok
            else "COMPRESSION_WATCH" if compression_now
            else "NO_PATTERN"
        )
        signals[i] = {
            "stage": stage, "breakout_close_above_prior_high": breakout,
            "volume_confirmation": volume_ok,
            "compression_within_prior_5_sessions": prior_compression,
            "breakout_after_compression": confirmed,
            "rvol_daily": round(rvol, 3) if rvol is not None else None,
            "prior_20_high": round(resistance, 4),
            "prior_20_low": round(support, 4),
        }

    current = signals[-1]
    if current is None:
        return _base("NOT_ENOUGH_WIDTH_HISTORY")
    result = _base("COMPLETED_OHLCV_CONTEXT")
    result.update({
        **current, "status": "RESEARCH_ONLY",
        "source_last_daily_bar": frame.index[-1].date().isoformat(),
    })

    # Replay signal decisions at each historical candle close; outcomes use
    # ONLY the five completed sessions AFTER that candle. One signal per bar;
    # no filling, broker spread or option execution assumptions.
    matured: list[tuple[float, float]] = []
    for i in range(len(signals) - HORIZON_SESSIONS):
        x = signals[i]
        if not x or not x["breakout_after_compression"]:
            continue
        future = slice(i + 1, i + HORIZON_SESSIONS + 1)
        best = (float(np.max(high[future])) / close[i] - 1) * 100
        worst = (float(np.min(low[future])) / close[i] - 1) * 100
        matured.append((best, worst))
    result["historical_replay"].update({
        "matured_events": len(matured),
        # A tiny sample is not evidence of repeatable gains; disclose sample
        # count but suppress medians until five independent signal instances.
        "median_best_forward_5session_pct": (
            round(median(x[0] for x in matured), 3) if len(matured) >= 5 else None
        ),
        "median_worst_forward_5session_pct": (
            round(median(x[1] for x in matured), 3) if len(matured) >= 5 else None
        ),
        "minimum_descriptive_samples": 5,
        "warning": (
            "In-sample descriptive OHLC excursions, not trade returns. "
            "No separate walk-forward or transaction-cost validation."
        ),
    })
    return result
