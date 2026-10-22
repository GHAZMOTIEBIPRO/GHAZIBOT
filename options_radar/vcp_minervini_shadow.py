"""Qullamaggie/VCP and Minervini-inspired completed-daily-bar research.

Independent implementation inspired by public trading methodologies; no
upstream code copied, additional fetches, option-quote promotion, implied
success probabilities, or live CALL/PUT signals.
"""
from __future__ import annotations

import math

import pandas as pd

STAGES = frozenset({"INSUFFICIENT", "NO_SETUP", "DEVELOPING", "TIGHT_WATCH"})


def _valid(frame: pd.DataFrame) -> bool:
    if (not isinstance(frame, pd.DataFrame) or len(frame) < 70
            or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None or not frame.index.is_monotonic_increasing
            or frame.index.has_duplicates
            or not all(c in frame for c in ("Open", "High", "Low", "Close", "Volume"))):
        return False
    samples = frame[["Open", "High", "Low", "Close", "Volume"]].tail(85)
    for row in samples.itertuples(index=False, name=None):
        o, h, l, c, v = row
        if (not all(isinstance(x, (int, float)) or hasattr(x, "__float__") for x in row)
                or not all(math.isfinite(float(x)) for x in row)
                or min(o, h, l, c) <= 0 or v < 0
                or h < max(o, c) or l > min(o, c) or l > h):
            return False
    return True


def _mean(numbers: list[float]) -> float:
    return sum(numbers) / len(numbers)


def _ema(closes: list[float], n: int) -> float:
    value = _mean(closes[:n])
    k = 2 / (n + 1)
    for close in closes[n:]:
        value = k * close + (1 - k) * value
    return value


def _atr14(values: list[tuple[float, float, float, float, float]]) -> list[float]:
    ranges = []
    for i in range(1, len(values)):
        _, high, low, _, _ = values[i]
        previous_close = values[i - 1][3]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return ranges


def vcp_trend_shadow(frame: pd.DataFrame, *, source_family: str = "yahoo") -> dict:
    if source_family not in {"yahoo", "alpaca_iex", "alpaca_historical_sip"}:
        raise ValueError("unknown OHLCV family; no implicit source upgrade")
    base = {
        "schema": "ghazi.vcp_minervini_shadow.v1",
        "available": False, "stage": "INSUFFICIENT", "source_last_daily_bar": None,
        "source_family": source_family, "research_only": True,
        "independent_confirmation": False, "option_execution_eligible": False,
        "data_authority": "COMPLETED_DAILY_OHLCV_RESEARCH_ONLY",
        "volume_dry_up": None, "atr_contraction": None, "ema_stack": None,
        "near_55d_high": None, "volume_ratio": None, "atr_ratio": None,
        "distance_from_55d_high_pct": None, "pivot": None, "closed_bars": 0,
        "reasons": [],
    }
    if not _valid(frame):
        return base
    rows = [
        tuple(float(x) for x in row) for row in
        frame[["Open", "High", "Low", "Close", "Volume"]].tail(85).itertuples(index=False, name=None)
    ]
    closes = [r[3] for r in rows]
    volumes = [r[4] for r in rows]
    last = closes[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    # Independent, non-overlapping realized ranges. Final candle is CLOSED.
    trs = _atr14(rows)
    atr_recent = _mean(trs[-14:])
    atr_before = _mean(trs[-28:-14])
    vol_recent = _mean(volumes[-10:])
    vol_before = _mean(volumes[-40:-10])
    prior_55_high = max(r[1] for r in rows[-56:-1])  # exclude current bar
    if not all(math.isfinite(x) and x > 0 for x in (
        last, atr_recent, atr_before, vol_before, prior_55_high
    )):
        return base
    atr_ratio = atr_recent / atr_before
    volume_ratio = vol_recent / vol_before
    distance = 100.0 * (prior_55_high - last) / prior_55_high
    ema_stack = last > ema20 > ema50
    # Negative distance means it has already closed above prior resistance.
    near_pivot = -0.5 <= distance <= 6.0
    compressed = atr_ratio <= 0.85
    dry = volume_ratio <= 0.85
    factors = sum((ema_stack, near_pivot, compressed, dry))
    stage = ("TIGHT_WATCH" if factors == 4 else
             "DEVELOPING" if factors >= 2 else "NO_SETUP")
    reasons = [
        ("EMA20 فوق EMA50 والإغلاق فوقهما" if ema_stack else "لا يوجد اصطفاف EMA20/50 صاعد"),
        ("الإغلاق قريب من قمة 55 جلسة سابقة" if near_pivot else
         "الإغلاق بعيد عن قمة 55 جلسة أو اخترقها بالفعل"),
        ("مدى الحركة ينكمش" if compressed else "انكماش ATR غير كافٍ"),
        ("حجم التداول ينكمش" if dry else "انكماش الحجم غير كافٍ"),
    ]
    return {
        **base, "available": True, "stage": stage,
        "source_last_daily_bar": frame.index[-1].date().isoformat(),
        "closed_bars": len(rows), "ema_stack": ema_stack,
        "near_55d_high": near_pivot, "atr_contraction": compressed,
        "volume_dry_up": dry, "volume_ratio": round(volume_ratio, 3),
        "atr_ratio": round(atr_ratio, 3),
        "distance_from_55d_high_pct": round(distance, 2),
        "pivot": round(prior_55_high, 4),
        "reasons": reasons,
    }
