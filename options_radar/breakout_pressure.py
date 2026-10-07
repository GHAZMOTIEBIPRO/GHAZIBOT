from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BreakoutPressureSnapshot:
    available: bool
    side: str
    score: float
    atr_compression_ratio: float | None
    range_tightness_pct: float | None
    volume_contraction_ratio: float | None
    breakout_distance_atr: float | None
    weekly_confluence: bool
    reasons: tuple[str, ...]


def _numeric(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame:
            return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(float("nan"), index=frame.index, dtype="float64")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _tightness_score(range_pct: float) -> float:
    if range_pct <= 5.0:
        return 20.0
    if range_pct >= 18.0:
        return 0.0
    return 20.0 * (18.0 - range_pct) / 13.0


def _compression_score(ratio: float) -> float:
    if ratio <= 0.65:
        return 25.0
    if ratio >= 1.05:
        return 0.0
    return 25.0 * (1.05 - ratio) / 0.40


def _proximity_score(distance_atr: float) -> float:
    if -0.20 <= distance_atr <= 0.80:
        return 20.0
    if -0.50 <= distance_atr <= 1.50:
        return 12.0
    if -1.00 <= distance_atr <= 2.50:
        return 5.0
    return 0.0


def analyze_breakout_pressure(
    history: pd.DataFrame,
    side: str,
    *,
    relative_strength_20d: Any = 0.0,
) -> BreakoutPressureSnapshot:
    """Measure pre-breakout coil pressure from the underlying only.

    This is an independent implementation inspired by common momentum-breakout
    research patterns: ATR compression, range tightness, volume contraction,
    proximity to a prior breakout level, trend alignment, and weekly confluence.
    It does not copy external scanner code and does not use option data.
    """
    normalized_side = str(side or "").strip().lower()
    if normalized_side not in {"call", "put"} or history is None or history.empty:
        return BreakoutPressureSnapshot(
            False,
            normalized_side,
            0.0,
            None,
            None,
            None,
            None,
            False,
            (),
        )

    close = _numeric(history, "Close", "close")
    high = _numeric(history, "High", "high")
    low = _numeric(history, "Low", "low")
    volume = _numeric(history, "Volume", "volume")
    frame = pd.DataFrame(
        {"close": close, "high": high, "low": low, "volume": volume},
        index=history.index,
    ).dropna(subset=["close", "high", "low"])

    if len(frame) < 25:
        return BreakoutPressureSnapshot(
            False,
            normalized_side,
            0.0,
            None,
            None,
            None,
            None,
            False,
            ("insufficient_history",),
        )

    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = float(true_range.tail(14).mean())
    long_atr = float(true_range.tail(min(50, len(true_range))).mean())
    short_atr = float(true_range.tail(5).mean())
    if atr14 <= 0 or long_atr <= 0:
        return BreakoutPressureSnapshot(
            False,
            normalized_side,
            0.0,
            None,
            None,
            None,
            None,
            False,
            ("invalid_atr",),
        )

    compression_ratio = short_atr / long_atr
    latest_close = float(frame["close"].iloc[-1])
    range_tightness_pct = (
        float(frame["high"].tail(10).max() - frame["low"].tail(10).min())
        / latest_close
        * 100.0
    )

    clean_volume = frame["volume"].dropna().clip(lower=0)
    volume_contraction_ratio: float | None = None
    volume_expansion_ratio: float | None = None
    if len(clean_volume) >= 20:
        average20 = float(clean_volume.tail(20).mean())
        average5 = float(clean_volume.tail(5).mean())
        if average20 > 0:
            volume_contraction_ratio = average5 / average20
            volume_expansion_ratio = float(clean_volume.iloc[-1]) / average20

    prior_high = float(frame["high"].shift(1).rolling(20).max().iloc[-1])
    prior_low = float(frame["low"].shift(1).rolling(20).min().iloc[-1])
    if normalized_side == "call":
        breakout_distance_atr = (prior_high - latest_close) / atr14
    else:
        breakout_distance_atr = (latest_close - prior_low) / atr14

    ema20 = float(frame["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(frame["close"].ewm(span=50, adjust=False).mean().iloc[-1])
    trend_aligned = (
        latest_close > ema20 > ema50
        if normalized_side == "call"
        else latest_close < ema20 < ema50
    )

    weekly_confluence = False
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame) >= 50:
        weekly_close = frame["close"].resample("W-FRI").last().dropna()
        if len(weekly_close) >= 10:
            weekly_fast = float(
                weekly_close.ewm(span=4, adjust=False).mean().iloc[-1]
            )
            weekly_slow = float(
                weekly_close.ewm(span=10, adjust=False).mean().iloc[-1]
            )
            weekly_last = float(weekly_close.iloc[-1])
            weekly_confluence = (
                weekly_last > weekly_fast > weekly_slow
                if normalized_side == "call"
                else weekly_last < weekly_fast < weekly_slow
            )

    score = _compression_score(compression_ratio)
    score += _tightness_score(range_tightness_pct)
    score += _proximity_score(breakout_distance_atr)

    reasons: list[str] = []
    if compression_ratio <= 0.80:
        reasons.append(f"ATR compression {compression_ratio:.2f}x")
    if range_tightness_pct <= 8.0:
        reasons.append(f"10D range tight {range_tightness_pct:.1f}%")

    if volume_contraction_ratio is not None:
        if volume_contraction_ratio <= 0.70:
            score += 15.0
            reasons.append(
                f"volume contraction {volume_contraction_ratio:.2f}x"
            )
        elif volume_contraction_ratio <= 0.90:
            score += 9.0

    if trend_aligned:
        score += 15.0
        reasons.append("trend stack aligned")

    if weekly_confluence:
        score += 10.0
        reasons.append("weekly confluence")

    try:
        rs20 = float(relative_strength_20d)
    except (TypeError, ValueError):
        rs20 = 0.0
    aligned_rs = rs20 >= 0.01 if normalized_side == "call" else rs20 <= -0.01
    if aligned_rs:
        score += 5.0
        reasons.append("relative strength aligned")

    if (
        volume_expansion_ratio is not None
        and volume_expansion_ratio >= 1.30
        and -0.35 <= breakout_distance_atr <= 0.80
    ):
        score += 5.0
        reasons.append(f"breakout volume wake-up {volume_expansion_ratio:.2f}x")

    if -0.20 <= breakout_distance_atr <= 0.80:
        reasons.append(f"near trigger {breakout_distance_atr:.2f} ATR")

    return BreakoutPressureSnapshot(
        True,
        normalized_side,
        round(_clamp(score), 2),
        round(compression_ratio, 4),
        round(range_tightness_pct, 4),
        (
            round(volume_contraction_ratio, 4)
            if volume_contraction_ratio is not None
            else None
        ),
        round(breakout_distance_atr, 4),
        weekly_confluence,
        tuple(reasons),
    )
