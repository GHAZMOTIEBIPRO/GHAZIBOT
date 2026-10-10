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
    research_v3: dict[str, Any] | None = None


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




def _research_setup_v3(
    frame: pd.DataFrame,
    *,
    side: str,
    latest_close: float,
    breakout_distance_atr: float,
    volume_contraction_ratio: float | None,
) -> dict[str, Any]:
    """Independent shadow setup inspired by permissively licensed momentum screeners."""

    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    enough_200 = len(frame) >= 200

    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = (
        float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        if enough_200
        else None
    )
    if side == "call":
        ema_stack = (
            latest_close > ema20 > ema50 > ema200
            if ema200 is not None
            else latest_close > ema20 > ema50
        )
    else:
        ema_stack = (
            latest_close < ema20 < ema50 < ema200
            if ema200 is not None
            else latest_close < ema20 < ema50
        )

    comparisons = pd.DataFrame(
        {
            "higher_high": high > high.shift(1),
            "higher_low": low > low.shift(1),
            "lower_high": high < high.shift(1),
            "lower_low": low < low.shift(1),
        }
    ).tail(20)
    if side == "call":
        structure_hits = (
            comparisons["higher_high"].astype(int)
            + comparisons["higher_low"].astype(int)
        ) / 2.0
    else:
        structure_hits = (
            comparisons["lower_high"].astype(int)
            + comparisons["lower_low"].astype(int)
        ) / 2.0
    hh_hl_ratio = float(structure_hits.mean()) if len(structure_hits) else 0.0

    def range_pct(window: int) -> float | None:
        if len(frame) < window:
            return None
        segment = frame.tail(window)
        denominator = float(segment["close"].iloc[-1])
        if denominator <= 0:
            return None
        return float(segment["high"].max() - segment["low"].min()) / denominator

    range5 = range_pct(5)
    range10 = range_pct(10)
    range20 = range_pct(20)
    vcp_like = bool(
        range5 is not None
        and range10 is not None
        and range20 is not None
        and range5 < range10 < range20
    )

    rolling_mean = close.rolling(20).mean()
    rolling_std = close.rolling(20).std(ddof=0)
    bandwidth = (4.0 * rolling_std / rolling_mean.replace(0, float("nan"))).dropna()
    current_bandwidth = float(bandwidth.iloc[-1]) if len(bandwidth) else None
    bandwidth_percentile = None
    if current_bandwidth is not None and len(bandwidth) >= 20:
        history = bandwidth.tail(60)
        bandwidth_percentile = float(
            (history <= current_bandwidth).sum() / len(history) * 100.0
        )

    year_window = frame.tail(min(252, len(frame)))
    high_52w = float(year_window["high"].max()) if len(year_window) else latest_close
    low_52w = float(year_window["low"].min()) if len(year_window) else latest_close
    if side == "call":
        distance_52w_pct = (
            (high_52w - latest_close) / latest_close * 100.0
            if latest_close > 0
            else None
        )
    else:
        distance_52w_pct = (
            (latest_close - low_52w) / latest_close * 100.0
            if latest_close > 0
            else None
        )

    quality_flags = {
        "ema_stack": bool(ema_stack),
        "price_structure": hh_hl_ratio >= 0.55,
        "vcp_like": vcp_like,
        "volume_dry_up": (
            volume_contraction_ratio is not None
            and volume_contraction_ratio <= 0.80
        ),
        "bollinger_squeeze": (
            bandwidth_percentile is not None
            and bandwidth_percentile <= 30.0
        ),
        "near_breakout": -0.20 <= breakout_distance_atr <= 0.80,
        "near_52w_extreme": (
            distance_52w_pct is not None and distance_52w_pct <= 8.0
        ),
    }
    quality_count = sum(1 for value in quality_flags.values() if value)

    if breakout_distance_atr < -0.75:
        stage = "EXTENDED"
    elif quality_count >= 5 and quality_flags["near_breakout"]:
        stage = "ARMED"
    elif quality_count >= 3:
        stage = "COILING"
    else:
        stage = "RESEARCH"

    return {
        "version": "EXPLOSION_SETUP_V3_SHADOW",
        "stage": stage,
        "quality_count": quality_count,
        "quality_flags": quality_flags,
        "hh_hl_structure_ratio": round(hh_hl_ratio, 4),
        "range_5d_pct": round(range5 * 100.0, 4) if range5 is not None else None,
        "range_10d_pct": round(range10 * 100.0, 4) if range10 is not None else None,
        "range_20d_pct": round(range20 * 100.0, 4) if range20 is not None else None,
        "bollinger_bandwidth_20": (
            round(current_bandwidth, 6)
            if current_bandwidth is not None
            else None
        ),
        "bollinger_bandwidth_percentile_60": (
            round(bandwidth_percentile, 2)
            if bandwidth_percentile is not None
            else None
        ),
        "distance_to_52w_extreme_pct": (
            round(distance_52w_pct, 4)
            if distance_52w_pct is not None
            else None
        ),
        "ema200_available": enough_200,
        "research_only": True,
        "live_score_adjustment": False,
        "decision_authority": False,
        "score_is_probability": False,
    }


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

    research_v3 = _research_setup_v3(
        frame,
        side=normalized_side,
        latest_close=latest_close,
        breakout_distance_atr=breakout_distance_atr,
        volume_contraction_ratio=volume_contraction_ratio,
    )

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
        research_v3,
    )
