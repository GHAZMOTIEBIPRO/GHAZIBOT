from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TechnicalSnapshot:
    symbol: str
    close: float
    ema9: float
    ema21: float
    ema50: float
    ema200: float
    rsi14: float
    macd: float
    macd_signal: float
    atr14: float
    realized_vol20: float
    relative_volume20: float
    resistance20: float
    support20: float
    direction: str
    catalyst: str
    catalyst_score: float
    breakout: bool


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["Close"].shift(1)
    ranges = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def analyze_technical(symbol: str, history: pd.DataFrame) -> TechnicalSnapshot:
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(history.columns)
    if missing:
        raise ValueError(f"Missing price columns for {symbol}: {sorted(missing)}")
    if len(history) < 60:
        raise ValueError(f"Not enough history for {symbol}: {len(history)} rows")

    frame = history.copy().dropna(subset=["Close"])
    close = frame["Close"].astype(float)
    volume = frame["Volume"].astype(float)
    ema9, ema21, ema50, ema200 = (_ema(close, n) for n in (9, 21, 50, 200))
    rsi14 = _rsi(close, 14)
    macd_line = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd_line, 9)
    atr14 = _atr(frame, 14)
    realized_vol20 = close.pct_change().rolling(20).std() * math.sqrt(252)
    relative_volume20 = volume / volume.rolling(20).mean()

    current = float(close.iloc[-1])
    resistance = float(frame["High"].shift(1).rolling(20).max().iloc[-1])
    support = float(frame["Low"].shift(1).rolling(20).min().iloc[-1])
    values = [float(x.iloc[-1]) for x in (ema9, ema21, ema50)]
    e9, e21, e50 = values
    e200 = float(ema200.iloc[-1]) if pd.notna(ema200.iloc[-1]) else e50
    rsi = float(rsi14.iloc[-1])
    macd = float(macd_line.iloc[-1])
    signal = float(macd_signal.iloc[-1])
    atr = float(atr14.iloc[-1])
    rvol = float(relative_volume20.iloc[-1])
    rv = float(realized_vol20.iloc[-1])

    bullish_stack = current > e21 > e50 and e9 > e21
    bearish_stack = current < e21 < e50 and e9 < e21
    bullish_breakout = current > resistance and rvol >= 1.15
    bearish_breakdown = current < support and rvol >= 1.15
    bullish_momentum = macd > signal and 52 <= rsi <= 75
    bearish_momentum = macd < signal and 25 <= rsi <= 48

    score = 0.0
    reasons: list[str] = []
    if bullish_stack:
        score += 7; reasons.append("bullish EMA stack")
    if bearish_stack:
        score -= 7; reasons.append("bearish EMA stack")
    if bullish_breakout:
        score += 9; reasons.append("20-day breakout with relative volume")
    if bearish_breakdown:
        score -= 9; reasons.append("20-day breakdown with relative volume")
    if bullish_momentum:
        score += 4; reasons.append("MACD/RSI bullish momentum")
    if bearish_momentum:
        score -= 4; reasons.append("MACD/RSI bearish momentum")

    direction = "bullish" if score >= 5 else "bearish" if score <= -5 else "neutral"
    return TechnicalSnapshot(
        symbol, current, e9, e21, e50, e200, rsi, macd, signal, atr, rv, rvol,
        resistance, support, direction,
        "; ".join(reasons) if reasons else "No strong technical catalyst",
        min(20.0, abs(score)), bullish_breakout or bearish_breakdown,
    )


def market_regime(spy: TechnicalSnapshot, qqq: TechnicalSnapshot, vix_close: float) -> str:
    bullish = spy.direction == "bullish" and qqq.direction in {"bullish", "neutral"}
    bearish = spy.direction == "bearish" and qqq.direction in {"bearish", "neutral"}
    if bullish and vix_close < 25:
        return "risk_on"
    if bearish or vix_close >= 30:
        return "risk_off"
    return "mixed"
