from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .interest_factors import finviz_style_profile


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def advanced_interest_profile(history: pd.DataFrame) -> dict[str, Any]:
    """Extend Finviz-style factors with quality-of-move diagnostics.

    Finviz definitions are used as a methodology reference only. All values are
    computed locally from the radar's OHLCV data; no Finviz page is scraped.
    """

    profile = finviz_style_profile(history)
    required = {"Open", "High", "Low", "Close", "Volume"}
    if history is None or history.empty or not required.issubset(history.columns):
        return profile

    frame = history[["Open", "High", "Low", "Close", "Volume"]].copy()
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["High", "Low", "Close"])
    if len(frame) < 30:
        return profile

    close = frame["Close"]
    high = frame["High"]
    low = frame["Low"]
    volume = frame["Volume"].fillna(0.0)
    current = _finite(close.iloc[-1])
    latest_range = max(0.0, _finite(high.iloc[-1] - low.iloc[-1]))
    prior_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prior_close).abs(), (low - prior_close).abs()], axis=1
    ).max(axis=1)
    atr14 = _finite(true_range.tail(14).mean())
    range_expansion = latest_range / atr14 if atr14 else 0.0

    recent_volume = _finite(volume.tail(5).mean())
    baseline_volume = _finite(volume.iloc[-25:-5].mean())
    volume_acceleration = recent_volume / baseline_volume if baseline_volume else 0.0

    dollar_volume = close * volume
    current_dollar = _finite(dollar_volume.iloc[-1])
    avg_dollar20 = _finite(dollar_volume.tail(20).mean())
    turnover_ratio = current_dollar / avg_dollar20 if avg_dollar20 else 0.0

    sma20 = _finite(close.tail(20).mean(), current)
    closes_above20 = float((close.tail(20) > sma20).mean())
    trend_quality_call = closes_above20
    trend_quality_put = 1.0 - closes_above20

    day_span = max(_finite(high.iloc[-1] - low.iloc[-1]), current * 0.001)
    close_location = (_finite(close.iloc[-1]) - _finite(low.iloc[-1])) / day_span
    close_location = max(0.0, min(1.0, close_location))

    attention = float(profile.get("attention_score", 0.0))
    call_score = float(profile.get("call_interest_score", 0.0))
    put_score = float(profile.get("put_interest_score", 0.0))
    attention_factors = list(profile.get("attention_factors", []))
    upside = list(profile.get("upside_factors", []))
    downside = list(profile.get("downside_factors", []))

    if volume_acceleration >= 1.8:
        attention += 4
        attention_factors.append("تسارع حجم 5 أيام ≥1.8x")
    elif volume_acceleration >= 1.3:
        attention += 2
        attention_factors.append("تسارع حجم 5 أيام")

    if turnover_ratio >= 2.0:
        attention += 4
        attention_factors.append("تسارع السيولة الدولارية ≥2x")
    elif turnover_ratio >= 1.4:
        attention += 2
        attention_factors.append("سيولة يومية أعلى من المعتاد")

    if range_expansion >= 1.6:
        attention += 3
        attention_factors.append("اتساع نطاق سعري مؤكد")
    elif range_expansion >= 1.2:
        attention += 1

    if trend_quality_call >= 0.75:
        call_score += 3
        upside.append("ثبات فوق SMA20 في أغلب الجلسات")
    if trend_quality_put >= 0.75:
        put_score += 3
        downside.append("ثبات تحت SMA20 في أغلب الجلسات")

    rel_volume = float(profile.get("finviz_relative_volume", 0.0) or 0.0)
    day_performance = float(profile.get("performance_day", 0.0) or 0.0)
    if rel_volume >= 1.5 and day_performance > 0.02 and close_location >= 0.75:
        call_score += 4
        upside.append("إغلاق قرب أعلى الجلسة مع حجم غير معتاد")
    if rel_volume >= 1.5 and day_performance < -0.02 and close_location <= 0.25:
        put_score += 4
        downside.append("إغلاق قرب أدنى الجلسة مع حجم غير معتاد")

    # Penalize noisy micro-cap style moves unless another layer supplies a strong
    # official event. The event layer can still rescue these names explicitly.
    if current < 5 and rel_volume >= 4 and avg_dollar20 < 10_000_000:
        attention = max(0.0, attention - 6)
        attention_factors.append("ضوضاء محتملة: سعر منخفض وحجم متطرف")

    profile.update(
        {
            "attention_score": round(max(0.0, min(30.0, attention)), 2),
            "call_interest_score": round(max(0.0, min(30.0, call_score)), 2),
            "put_interest_score": round(max(0.0, min(30.0, put_score)), 2),
            "attention_factors": list(dict.fromkeys(attention_factors)),
            "upside_factors": list(dict.fromkeys(upside)),
            "downside_factors": list(dict.fromkeys(downside)),
            "volume_acceleration_5d": round(volume_acceleration, 4),
            "dollar_turnover_ratio": round(turnover_ratio, 4),
            "range_expansion": round(range_expansion, 4),
            "close_location": round(close_location, 4),
            "trend_quality_call": round(trend_quality_call, 4),
            "trend_quality_put": round(trend_quality_put, 4),
            "attention_method": "Finviz-style OHLCV + quality-of-move overlay",
        }
    )
    return profile
