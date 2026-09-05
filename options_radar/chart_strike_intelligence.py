from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _normalized_ohlcv(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    out = frame[list(required)].copy().sort_index()
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    return out


def _resample_15m(frame: pd.DataFrame) -> pd.DataFrame:
    out = _normalized_ohlcv(frame)
    if out.empty or not isinstance(out.index, pd.DatetimeIndex):
        return pd.DataFrame()
    resampled = out.resample("15min").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    return resampled.dropna(subset=["Open", "High", "Low", "Close"])


def _candle_pattern(frame: pd.DataFrame) -> tuple[str, float]:
    if frame is None or len(frame) < 2:
        return "none", 0.0
    previous = frame.iloc[-2]
    current = frame.iloc[-1]
    o = _number(current.get("Open"))
    h = _number(current.get("High"))
    l = _number(current.get("Low"))
    c = _number(current.get("Close"))
    po = _number(previous.get("Open"))
    pc = _number(previous.get("Close"))
    candle_range = max(h - l, 1e-9)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    body_ratio = body / candle_range

    bullish_engulfing = pc < po and c > o and o <= pc and c >= po
    bearish_engulfing = pc > po and c < o and o >= pc and c <= po
    if bullish_engulfing:
        return "bullish_engulfing", 1.0
    if bearish_engulfing:
        return "bearish_engulfing", -1.0
    if body_ratio <= 0.12:
        return "doji", 0.0
    if lower >= body * 2.0 and upper <= max(body, candle_range * 0.15) and c >= o:
        return "hammer", 0.75
    if upper >= body * 2.0 and lower <= max(body, candle_range * 0.15) and c <= o:
        return "shooting_star", -0.75
    if body_ratio >= 0.78:
        return ("bullish_marubozu", 0.70) if c > o else ("bearish_marubozu", -0.70)
    return ("bullish_body", 0.25) if c > o else ("bearish_body", -0.25)


def _session_vwap(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    working = frame
    if isinstance(frame.index, pd.DatetimeIndex):
        latest_date = frame.index[-1].date()
        same_session = frame[frame.index.date == latest_date]
        if not same_session.empty:
            working = same_session
    volume = working["Volume"].fillna(0)
    total_volume = float(volume.sum())
    if total_volume <= 0:
        return None
    typical = (working["High"] + working["Low"] + working["Close"]) / 3.0
    return float((typical * volume).sum() / total_volume)


def _timeframe_context(
    frame: pd.DataFrame,
    *,
    label: str,
    use_vwap: bool,
) -> dict[str, Any]:
    frame = _normalized_ohlcv(frame)
    minimum = 25
    if len(frame) < minimum:
        return {"label": label, "available": False, "rows": len(frame), "score": 0.0}

    close = frame["Close"]
    volume = frame["Volume"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    latest = float(close.iloc[-1])
    e9 = float(ema9.iloc[-1])
    e21 = float(ema21.iloc[-1])
    previous_high = float(frame["High"].shift(1).rolling(20).max().iloc[-1])
    previous_low = float(frame["Low"].shift(1).rolling(20).min().iloc[-1])
    avg_volume = float(volume.shift(1).rolling(20).mean().iloc[-1])
    relative_volume = float(volume.iloc[-1] / avg_volume) if avg_volume > 0 else 0.0
    vwap = _session_vwap(frame) if use_vwap else None
    pattern, pattern_bias = _candle_pattern(frame)
    score = 0.0
    reasons: list[str] = []

    if latest > e9 > e21:
        score += 24.0
        reasons.append(f"{label}: السعر فوق EMA9>EMA21")
    elif latest < e9 < e21:
        score -= 24.0
        reasons.append(f"{label}: السعر تحت EMA9<EMA21")
    elif latest > e21:
        score += 8.0
    elif latest < e21:
        score -= 8.0

    breakout = latest > previous_high if math.isfinite(previous_high) else False
    breakdown = latest < previous_low if math.isfinite(previous_low) else False
    if breakout and relative_volume >= 1.15:
        score += 24.0
        reasons.append(f"{label}: اختراق 20 شمعة بفوليوم نسبي {relative_volume:.2f}×")
    elif breakdown and relative_volume >= 1.15:
        score -= 24.0
        reasons.append(f"{label}: كسر 20 شمعة بفوليوم نسبي {relative_volume:.2f}×")

    if vwap is not None and vwap > 0:
        if latest > vwap:
            score += 12.0
            reasons.append(f"{label}: فوق VWAP")
        elif latest < vwap:
            score -= 12.0
            reasons.append(f"{label}: تحت VWAP")

    if pattern_bias:
        score += 18.0 * pattern_bias
        reasons.append(f"{label}: نمط شمعة {pattern}")

    last_open = _number(frame["Open"].iloc[-1])
    if relative_volume >= 1.5:
        volume_bias = 1.0 if latest >= last_open else -1.0
        score += 12.0 * volume_bias
        reasons.append(f"{label}: توسع فوليوم {relative_volume:.2f}×")

    score = _clamp(score)
    direction = "bullish" if score >= 18 else "bearish" if score <= -18 else "neutral"
    return {
        "label": label,
        "available": True,
        "rows": len(frame),
        "close": round(latest, 6),
        "ema9": round(e9, 6),
        "ema21": round(e21, 6),
        "vwap": round(vwap, 6) if vwap is not None else None,
        "relative_volume": round(relative_volume, 4),
        "pattern": pattern,
        "pattern_bias": round(pattern_bias, 3),
        "breakout": bool(breakout),
        "breakdown": bool(breakdown),
        "score": round(score, 2),
        "direction": direction,
        "reasons_ar": reasons,
    }


def build_chart_context(
    symbol: str,
    *,
    fetcher: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build free chart-first context using two external bar fetches only.

    We fetch daily and 5-minute data. Fifteen-minute bars are resampled locally
    from the 5-minute frame, reducing provider calls while preserving a true
    multi-timeframe read. Failures remain research degradation, not fabricated data.
    """
    end = now or datetime.now(timezone.utc)
    daily = pd.DataFrame()
    intraday = pd.DataFrame()
    sources: dict[str, str] = {}
    errors: dict[str, str] = {}
    try:
        result = fetcher.fetch_stock_bars(
            symbol,
            interval="1d",
            start=end - timedelta(days=420),
            end=end,
        )
        daily = result.data
        sources["1d"] = str(result.source)
    except Exception as exc:
        errors["1d"] = f"{type(exc).__name__}: {exc}"
    try:
        result = fetcher.fetch_stock_bars(
            symbol,
            interval="5m",
            start=end - timedelta(days=7),
            end=end,
        )
        intraday = result.data
        sources["5m"] = str(result.source)
        sources["15m"] = f"resampled_from_5m:{result.source}"
    except Exception as exc:
        errors["5m"] = f"{type(exc).__name__}: {exc}"

    contexts = {
        "1d": _timeframe_context(daily, label="1D", use_vwap=False),
        "15m": _timeframe_context(
            _resample_15m(intraday), label="15m", use_vwap=True
        ),
        "5m": _timeframe_context(intraday, label="5m", use_vwap=True),
    }
    weights = {"1d": 0.35, "15m": 0.35, "5m": 0.30}
    available = [key for key, value in contexts.items() if value.get("available")]
    used_weight = sum(weights[key] for key in available)
    aggregate = (
        sum(_number(contexts[key].get("score")) * weights[key] for key in available)
        / used_weight
        if used_weight > 0
        else 0.0
    )
    aggregate = _clamp(aggregate)
    direction = "bullish" if aggregate >= 18 else "bearish" if aggregate <= -18 else "neutral"
    reasons: list[str] = []
    for key in ("1d", "15m", "5m"):
        reasons.extend(list(contexts[key].get("reasons_ar") or [])[:3])

    aligned_volume = 0.0
    for key in available:
        context = contexts[key]
        rvol = _number(context.get("relative_volume"))
        score = _number(context.get("score"))
        if rvol >= 1.15:
            aligned_volume += min(25.0, (rvol - 1.0) * 25.0) * (1 if score >= 0 else -1)
    institutional_proxy = _clamp(50.0 + aggregate * 0.35 + aligned_volume, 0.0, 100.0)
    return {
        "symbol": str(symbol).upper(),
        "score": round(aggregate, 2),
        "direction": direction,
        "available_timeframes": len(available),
        "required_timeframes_for_strict": 2,
        "timeframes": contexts,
        "sources": sources,
        "errors": errors,
        "reasons_ar": reasons[:8],
        "institutional_activity_proxy_score": round(institutional_proxy, 2),
        "institutional_activity_proxy_only": True,
        "institutional_proxy_note": (
            "Derived from multi-timeframe price/VWAP/relative-volume behavior; "
            "it is not verified institutional order flow or ownership."
        ),
    }


def expected_move_1sigma(row: dict[str, Any], spot: float) -> float:
    iv = _number(row.get("iv"))
    dte = max(_number(row.get("dte")), 0.0)
    if spot <= 0 or iv <= 0 or dte <= 0:
        return 0.0
    return spot * iv * math.sqrt(dte / 365.0)


def enrich_contract_with_chart_and_strike(
    row: dict[str, Any],
    *,
    chart: dict[str, Any],
    gamma_map: dict[str, Any],
) -> dict[str, Any]:
    output = dict(row)
    side = str(output.get("option_type") or "").lower()
    strike = _number(output.get("strike"))
    spot = _number(gamma_map.get("spot") or output.get("underlying_price"))
    chart_score = _number(chart.get("score"))
    side_chart_alignment = chart_score / 100.0 * (1.0 if side == "call" else -1.0)
    expected = expected_move_1sigma(output, spot)
    strike_distance = abs(strike - spot)
    expected_ratio = strike_distance / expected if expected > 0 else None
    top_oi = [_number(value) for value in gamma_map.get("top_oi_strikes", [])]
    top_volume = [_number(value) for value in gamma_map.get("top_volume_strikes", [])]
    call_wall = _number(gamma_map.get("call_wall"), float("nan"))
    put_wall = _number(gamma_map.get("put_wall"), float("nan"))
    gamma_flip = _number(gamma_map.get("gamma_flip"), float("nan"))
    liquidity_strike = _number(gamma_map.get("liquidity_strike"), float("nan"))
    strike_liquidity = _number(output.get("strike_liquidity_score"))

    intelligence = 45.0
    reasons: list[str] = []
    if expected_ratio is not None:
        if expected_ratio <= 0.55:
            intelligence += 16.0
            reasons.append(
                f"السترايك داخل {expected_ratio:.2f}× من الحركة المتوقعة 1σ ({expected:.2f})"
            )
        elif expected_ratio <= 1.0:
            intelligence += 8.0
            reasons.append(f"السترايك داخل الحركة المتوقعة 1σ ({expected:.2f})")
        elif expected_ratio > 1.35:
            intelligence -= 14.0
            reasons.append(
                f"السترايك بعيد {expected_ratio:.2f}× عن الحركة المتوقعة؛ مخاطرة OTM أعلى"
            )

    if strike in top_oi:
        intelligence += 10.0
        reasons.append("السترايك ضمن أعلى مراكز OI في السلسلة")
    if strike in top_volume:
        intelligence += 10.0
        reasons.append("السترايك ضمن أعلى مراكز Volume الحالية")
    if math.isfinite(liquidity_strike) and strike == liquidity_strike:
        intelligence += 8.0
        reasons.append("هذا هو Liquidity Strike الأعلى بمزيج OI+Volume")
    if strike_liquidity >= 70:
        intelligence += 7.0
        reasons.append(f"سيولة السترايك قوية {strike_liquidity:.0f}/100")

    wall = call_wall if side == "call" else put_wall
    if math.isfinite(wall):
        distance = abs(strike - wall)
        if distance <= max(1.0, spot * 0.01):
            intelligence += 5.0
            reasons.append(f"قريب من {'Call' if side == 'call' else 'Put'} Wall عند {wall:g}")
    if math.isfinite(gamma_flip) and spot > 0:
        if side == "call" and spot >= gamma_flip:
            intelligence += 4.0
            reasons.append(f"السعر فوق Gamma Flip≈{gamma_flip:g}")
        elif side == "put" and spot <= gamma_flip:
            intelligence += 4.0
            reasons.append(f"السعر تحت Gamma Flip≈{gamma_flip:g}")
        else:
            intelligence -= 3.0

    intelligence += max(-8.0, min(8.0, side_chart_alignment * 8.0))
    if side_chart_alignment >= 0.35:
        reasons.insert(0, "اتجاه 1D/15m/5m متوافق بقوة مع جهة العقد")
    elif side_chart_alignment <= -0.35:
        reasons.insert(0, "الشارت متعدد الفريمات يعاكس جهة العقد")

    output.update(
        {
            "chart_first": True,
            "chart_direction": chart.get("direction"),
            "chart_score": round(chart_score, 2),
            "chart_side_alignment": round(side_chart_alignment, 4),
            "chart_available_timeframes": int(chart.get("available_timeframes") or 0),
            "chart_context": chart,
            "institutional_activity_proxy_score": _number(
                chart.get("institutional_activity_proxy_score")
            ),
            "institutional_activity_proxy_only": True,
            "expected_move_1sigma": round(expected, 4) if expected > 0 else None,
            "strike_distance_from_spot": round(strike_distance, 4),
            "strike_distance_expected_move_ratio": (
                round(expected_ratio, 4) if expected_ratio is not None else None
            ),
            "strike_intelligence_score": round(_clamp(intelligence, 0.0, 100.0), 2),
            "strike_reasons_ar": reasons[:8],
            "strike_selection_version": "chart_gamma_liquidity_v1",
        }
    )
    return output
