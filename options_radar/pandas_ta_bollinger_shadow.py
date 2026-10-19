"""Optional MIT-licensed pandas-ta-classic daily Bollinger-compression shadow.

This is price-history research, not independent source confirmation,
a signal probability, or a license to trade/rebroadcast market data.
"""
from __future__ import annotations

from importlib import import_module, metadata
from typing import Any

import numpy as np
import pandas as pd

MIN_ROWS = 60
REQUIRED = ("Open", "High", "Low", "Close")


def _version() -> str:
    try:
        return metadata.version("pandas-ta-classic")
    except metadata.PackageNotFoundError:
        return "not-installed"


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": "UNAVAILABLE",
        "reason": reason,
        "library": "xgboosted/pandas-ta-classic",
        "library_version": _version(),
        "research_only": True,
        "data_source_family": "yahoo",
        "independent_data_confirmation": False,
        "live_decision_authority": False,
        "options_execution_eligible": False,
        "width_pct": None,
        "compression_watch": None,
        "percentile_threshold_pct": None,
        "price_probability": None,
    }


def bollinger_compression_shadow(history: pd.DataFrame | None) -> dict[str, Any]:
    """Monitor unusually tight BB width using only *supplied completed* OHLC.

    The caller is responsible for filtering incomplete provider bars. We do
    not fetch market data, infer a live session, or boost live alert scores.
    """
    if history is None or history.empty or len(history) < MIN_ROWS:
        return _unavailable("INSUFFICIENT_COMPLETED_DAILY_BARS")
    if not isinstance(history.index, pd.DatetimeIndex):
        return _unavailable("NO_DATED_BAR_INDEX")
    if history.index.has_duplicates or not history.index.is_monotonic_increasing:
        return _unavailable("NON_MONOTONIC_OR_DUPLICATE_BARS")
    if not set(REQUIRED).issubset(history.columns):
        return _unavailable("MISSING_OHLC")
    frame = history[list(REQUIRED)].copy()
    for col in REQUIRED:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        return _unavailable("NONFINITE_OHLC")
    if ((frame[list(REQUIRED)] <= 0).any().any() or
            (frame["Low"] > frame[["Open", "Close"]].min(axis=1)).any() or
            (frame["High"] < frame[["Open", "Close"]].max(axis=1)).any()):
        return _unavailable("INVALID_CANDLE_BOUNDS")

    try:
        ta = import_module("pandas_ta_classic")
    except ImportError:
        return _unavailable("OPTIONAL_LIBRARY_NOT_INSTALLED")

    try:
        # Explicit talib=False: keep this independent *calculation* from the
        # existing TA-Lib shadow. Both still share the same Yahoo price input.
        bands = ta.bbands(frame["Close"], length=20, std=2, talib=False)
        if not isinstance(bands, pd.DataFrame):
            return _unavailable("BOLLINGER_RESULT_INVALID")
        cols = [key for key in bands.columns if str(key).startswith("BBB_")]
        if len(cols) != 1:
            return _unavailable("BOLLINGER_WIDTH_COLUMN_MISSING")
        widths = pd.to_numeric(bands[cols[0]], errors="coerce").dropna()
        if len(widths) < 41 or not np.isfinite(widths.to_numpy(dtype=float)).all():
            return _unavailable("INSUFFICIENT_BANDWIDTH_HISTORY")
        # Compare this completed bar with the *previous* forty observations.
        history_widths = widths.iloc[-41:-1]
        threshold = float(history_widths.quantile(0.25))
        latest = float(widths.iloc[-1])
        if threshold <= 0 or latest < 0:
            return _unavailable("INVALID_BOLLINGER_WIDTH")
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return _unavailable("BOLLINGER_CALCULATION_INVALID")

    return {
        "available": True,
        "status": "COMPRESSION_WATCH" if latest <= threshold else "NORMAL_WIDTH",
        "reason": "COMPLETED_DAILY_OHLC_RESEARCH",
        "library": "xgboosted/pandas-ta-classic",
        "library_version": _version(),
        "research_only": True,
        "data_source_family": "yahoo",
        "independent_data_confirmation": False,
        "live_decision_authority": False,
        "options_execution_eligible": False,
        "source_last_daily_bar": history.index[-1].date().isoformat(),
        "lookback_sessions": 40,
        "width_pct": round(latest, 3),
        "percentile_threshold_pct": round(threshold, 3),
        "compression_watch": bool(latest <= threshold),
        "price_probability": None,
        "disclaimer": (
            "Bollinger compression is a descriptive volatility contraction, "
            "not a price-direction forecast or a verified live option signal."
        ),
    }
