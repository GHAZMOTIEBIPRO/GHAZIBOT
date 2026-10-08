"""Optional TA-Lib shadow validation for BLACK BOX technical indicators.

This module is deliberately not part of the production decision path. It accepts
canonical OHLCV only, performs local calculations, and fails closed on invalid
inputs or an unavailable optional dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = frozenset({"Open", "High", "Low", "Close", "Volume"})


class TALibUnavailable(RuntimeError):
    """Raised when the optional TA-Lib dependency is not installed."""


@dataclass(frozen=True)
class TALibShadowSnapshot:
    """Reference values that can be compared with the native indicator path."""

    source: str
    rows: int
    ema9: float
    ema21: float
    ema50: float
    rsi14: float
    macd: float
    macd_signal: float
    atr14: float


def _load_talib() -> Any:
    try:
        return import_module("talib")
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise TALibUnavailable("TA-Lib is not installed for shadow validation") from exc


def _validated_frame(history: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(history.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    if len(history) < 50:
        raise ValueError(f"Not enough OHLCV history for shadow validation: {len(history)}")
    frame = history.loc[:, sorted(REQUIRED_COLUMNS)].copy()
    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise ValueError("OHLCV contains missing or non-numeric values")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("OHLCV contains non-finite values")
    if (frame["High"] < frame["Low"]).any():
        raise ValueError("OHLCV contains High below Low")
    if (frame[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (frame["Volume"] < 0).any():
        raise ValueError("Volume must not be negative")
    return frame


def calculate_shadow(history: pd.DataFrame) -> TALibShadowSnapshot:
    """Calculate TA-Lib reference indicators without network or side effects."""
    frame = _validated_frame(history)
    talib = _load_talib()
    close = frame["Close"].to_numpy(dtype=float)
    high = frame["High"].to_numpy(dtype=float)
    low = frame["Low"].to_numpy(dtype=float)
    ema9 = talib.EMA(close, timeperiod=9)[-1]
    ema21 = talib.EMA(close, timeperiod=21)[-1]
    ema50 = talib.EMA(close, timeperiod=50)[-1]
    rsi14 = talib.RSI(close, timeperiod=14)[-1]
    macd, macd_signal, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    atr14 = talib.ATR(high, low, close, timeperiod=14)[-1]
    values = [ema9, ema21, ema50, rsi14, macd[-1], macd_signal[-1], atr14]
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        raise ValueError("TA-Lib returned non-finite shadow values")
    return TALibShadowSnapshot(
        source="TA-Lib",
        rows=len(frame),
        ema9=float(ema9),
        ema21=float(ema21),
        ema50=float(ema50),
        rsi14=float(rsi14),
        macd=float(macd[-1]),
        macd_signal=float(macd_signal[-1]),
        atr14=float(atr14),
    )
