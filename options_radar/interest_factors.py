from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _return(series: pd.Series, periods: int) -> float:
    if len(series) <= periods:
        return 0.0
    start = _finite(series.iloc[-periods - 1])
    end = _finite(series.iloc[-1])
    return end / start - 1.0 if start else 0.0


def finviz_style_profile(history: pd.DataFrame) -> dict[str, Any]:
    """Build interest factors using public Finviz screener definitions.

    This does not scrape or redistribute Finviz data. It computes equivalent
    technical filters from the project's own OHLCV history: relative volume,
    moving-average structure, performance windows, ATR, and distance from
    52-week highs/lows.
    """

    required = {"Open", "High", "Low", "Close", "Volume"}
    if history is None or history.empty or not required.issubset(history.columns):
        return {
            "attention_score": 0.0,
            "call_interest_score": 0.0,
            "put_interest_score": 0.0,
            "upside_factors": [],
            "downside_factors": [],
        }

    frame = history[list(required)].copy()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    if len(frame) < 63:
        return {
            "attention_score": 0.0,
            "call_interest_score": 0.0,
            "put_interest_score": 0.0,
            "upside_factors": [],
            "downside_factors": [],
        }

    close = frame["Close"]
    high = frame["High"]
    low = frame["Low"]
    volume = frame["Volume"].fillna(0.0)
    current = _finite(close.iloc[-1])
    previous = _finite(close.iloc[-2], current)
    current_open = _finite(frame["Open"].iloc[-1], current)

    sma20 = _finite(close.tail(20).mean(), current)
    sma50 = _finite(close.tail(50).mean(), current)
    sma200 = _finite(close.tail(200).mean(), sma50)
    avg_volume20 = _finite(volume.tail(20).mean())
    avg_volume63 = _finite(volume.tail(63).mean())
    relative_volume = _finite(volume.iloc[-1] / avg_volume63) if avg_volume63 else 0.0
    avg_dollar_volume = _finite((close * volume).tail(20).mean())

    prior_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prior_close).abs(),
            (low - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = _finite(true_range.tail(14).mean())
    atr_pct = atr14 / current if current else 0.0

    high52 = _finite(high.tail(252).max(), current)
    low52 = _finite(low.tail(252).min(), current)
    distance_52w_high = current / high52 - 1.0 if high52 else 0.0
    distance_52w_low = current / low52 - 1.0 if low52 else 0.0
    performance_day = current / previous - 1.0 if previous else 0.0
    performance_week = _return(close, 5)
    performance_month = _return(close, 21)
    performance_quarter = _return(close, 63)
    gap_pct = current_open / previous - 1.0 if previous else 0.0

    prior_high20 = _finite(high.iloc[:-1].tail(20).max(), current)
    prior_low20 = _finite(low.iloc[:-1].tail(20).min(), current)
    breakout20 = current >= prior_high20 and prior_high20 > 0
    breakdown20 = current <= prior_low20 and prior_low20 > 0
    pullback_reclaim = (
        current > sma50 > sma200
        and _finite(low.tail(5).min(), current) <= sma20 * 1.02
        and current >= sma20
    )
    relief_rejection = (
        current < sma50 < sma200
        and _finite(high.tail(5).max(), current) >= sma20 * 0.98
        and current <= sma20
    )

    attention = 0.0
    upside = 0.0
    downside = 0.0
    attention_factors: list[str] = []
    upside_factors: list[str] = []
    downside_factors: list[str] = []

    if avg_dollar_volume >= 100_000_000:
        attention += 5
        attention_factors.append("سيولة دولارية مؤسسية")
    elif avg_dollar_volume >= 30_000_000:
        attention += 4
        attention_factors.append("سيولة دولارية مرتفعة")
    elif avg_dollar_volume >= 10_000_000:
        attention += 3
        attention_factors.append("سيولة دولارية جيدة")
    elif avg_dollar_volume >= 3_000_000:
        attention += 1
    else:
        attention -= 6
        attention_factors.append("سيولة ضعيفة")

    if relative_volume >= 2.0:
        attention += 7
        attention_factors.append("حجم استثنائي ≥2x")
    elif relative_volume >= 1.5:
        attention += 5
        attention_factors.append("حجم غير معتاد ≥1.5x")
    elif relative_volume >= 1.2:
        attention += 2
        attention_factors.append("ارتفاع الحجم")

    if abs(performance_day) >= 0.05:
        attention += 4
        attention_factors.append("حركة يومية ≥5%")
    elif abs(performance_day) >= 0.03:
        attention += 2
        attention_factors.append("حركة يومية ≥3%")

    if atr_pct >= 0.04:
        attention += 3
        attention_factors.append("ATR مرتفع")
    elif atr_pct >= 0.02:
        attention += 1

    if breakout20 or breakdown20:
        attention += 4
        attention_factors.append("كسر نطاق 20 يومًا")
    if distance_52w_high >= -0.10 or distance_52w_low <= 0.15:
        attention += 2
        attention_factors.append("قرب مستوى 52 أسبوعًا")
    if current < 2.0:
        attention -= 8
        attention_factors.append("سهم منخفض السعر عالي المخاطر")

    if current > sma20:
        upside += 2
        upside_factors.append("فوق SMA20")
    else:
        downside += 2
        downside_factors.append("تحت SMA20")
    if sma20 > sma50:
        upside += 3
        upside_factors.append("SMA20 فوق SMA50")
    elif sma20 < sma50:
        downside += 3
        downside_factors.append("SMA20 تحت SMA50")
    if sma50 > sma200:
        upside += 4
        upside_factors.append("SMA50 فوق SMA200")
    elif sma50 < sma200:
        downside += 4
        downside_factors.append("SMA50 تحت SMA200")

    if performance_week > 0.02:
        upside += 2
        upside_factors.append("أداء أسبوعي موجب")
    elif performance_week < -0.02:
        downside += 2
        downside_factors.append("أداء أسبوعي سالب")
    if performance_month > 0.05:
        upside += 3
        upside_factors.append("زخم شهري موجب")
    elif performance_month < -0.05:
        downside += 3
        downside_factors.append("زخم شهري سالب")
    if performance_quarter > 0.10:
        upside += 3
        upside_factors.append("زخم ربع سنوي موجب")
    elif performance_quarter < -0.10:
        downside += 3
        downside_factors.append("زخم ربع سنوي سالب")

    if breakout20:
        upside += 5
        upside_factors.append("اختراق 20 يومًا")
    if breakdown20:
        downside += 5
        downside_factors.append("كسر 20 يومًا")
    if pullback_reclaim:
        upside += 4
        upside_factors.append("ارتداد من المتوسط مع اتجاه رئيسي صاعد")
    if relief_rejection:
        downside += 4
        downside_factors.append("رفض ارتداد داخل اتجاه رئيسي هابط")
    if relative_volume >= 1.5:
        if performance_day > 0:
            upside += 3
            upside_factors.append("ارتفاع مؤكد بالحجم")
        elif performance_day < 0:
            downside += 3
            downside_factors.append("هبوط مؤكد بالحجم")
    if distance_52w_high >= -0.08:
        upside += 2
        upside_factors.append("قرب قمة 52 أسبوعًا")
    if distance_52w_low <= 0.12:
        downside += 2
        downside_factors.append("قرب قاع 52 أسبوعًا")

    extension20 = current / sma20 - 1.0 if sma20 else 0.0
    if performance_month > 0.35 or extension20 > 0.18:
        upside -= 6
        upside_factors.append("صعود ممتد يحتاج انتظار")
    if performance_month < -0.35 or extension20 < -0.18:
        downside -= 6
        downside_factors.append("هبوط ممتد يحتاج انتظار")

    return {
        "attention_score": round(max(0.0, min(25.0, attention)), 2),
        "call_interest_score": round(max(0.0, min(25.0, upside)), 2),
        "put_interest_score": round(max(0.0, min(25.0, downside)), 2),
        "attention_factors": attention_factors,
        "upside_factors": upside_factors,
        "downside_factors": downside_factors,
        "performance_day": round(performance_day, 6),
        "performance_week": round(performance_week, 6),
        "performance_month": round(performance_month, 6),
        "performance_quarter": round(performance_quarter, 6),
        "gap_pct": round(gap_pct, 6),
        "atr_pct": round(atr_pct, 6),
        "distance_52w_high": round(distance_52w_high, 6),
        "distance_52w_low": round(distance_52w_low, 6),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "sma200": round(sma200, 4),
        "finviz_relative_volume": round(relative_volume, 4),
        "finviz_avg_volume20": round(avg_volume20, 0),
        "finviz_avg_volume63": round(avg_volume63, 0),
        "finviz_avg_dollar_volume": round(avg_dollar_volume, 0),
        "breakout20": bool(breakout20),
        "breakdown20": bool(breakdown20),
        "pullback_reclaim": bool(pullback_reclaim),
        "relief_rejection": bool(relief_rejection),
    }
