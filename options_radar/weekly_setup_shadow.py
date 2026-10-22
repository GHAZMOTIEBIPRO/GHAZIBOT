"""Independent weekly context inspired by Qullamaggie; no upstream code copied.

Input is already-completed daily OHLCV. Never use a partial calendar week,
fill missing sessions, fetch data, or change daily scores/option authority.
"""
from __future__ import annotations

import math

import exchange_calendars as xcals
import pandas as pd


def weekly_setup_shadow(frame: pd.DataFrame, *, daily_stage: str) -> dict:
    base = {
        "schema": "ghazi.weekly_setup_shadow.v1", "available": False,
        "status": "INSUFFICIENT", "research_only": True,
        "independent_confirmation": False, "option_execution_eligible": False,
        "last_complete_week": None, "weeks_used": 0,
        "trend_up": None, "range_contraction": None, "range_ratio": None,
        "weekly_breakout": None,
    }
    columns = ["Open", "High", "Low", "Close", "Volume"]
    if (not isinstance(frame, pd.DataFrame) or len(frame) < 60
            or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
            or not frame.index.is_monotonic_increasing or frame.index.has_duplicates
            or not all(c in frame for c in columns)):
        return base
    daily = frame[columns].tail(130).copy()
    # The caller supplies complete daily candles, not intraday bars. Preserve
    # New York session dates rather than treating UTC midnight as a session.
    local = daily.index.tz_convert("America/New_York")
    dates = local.tz_localize(None).normalize()
    if dates.has_duplicates:
        return base
    daily.index = dates
    try:
        daily = daily.astype(float)
    except (TypeError, ValueError):
        return base
    for o, h, l, c, v in daily.itertuples(index=False, name=None):
        if (not all(math.isfinite(x) for x in (o, h, l, c, v))
                or min(o, h, l, c) <= 0 or v < 0
                or h < max(o, c) or l > min(o, c)):
            return base
    weekly = daily.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    })
    # A Friday holiday ending Thursday is deliberately deferred until the next
    # source session: conservative completeness, not an inferred Friday bar.
    weekly = weekly.loc[weekly.index <= dates[-1]].tail(12)
    if len(weekly) < 12 or weekly.isna().any().any():
        return base
    calendar = xcals.get_calendar("XNYS")
    try:
        for end in weekly.index:
            start = end - pd.Timedelta(days=4)
            expected = {s.date() for s in calendar.sessions_in_range(start, end)}
            actual = set(daily.loc[start:end].index.date)
            if not expected or actual != expected:
                return base
    except (ValueError, KeyError):
        return base
    closes = weekly.Close.tolist()
    ranges = [max(float(weekly.High.iloc[i] - weekly.Low.iloc[i]),
                  abs(float(weekly.High.iloc[i]) - closes[i - 1]),
                  abs(float(weekly.Low.iloc[i]) - closes[i - 1]))
              for i in range(1, len(weekly))]
    prior = sum(ranges[-6:-3]) / 3
    recent = sum(ranges[-3:]) / 3
    if prior <= 0:
        return base
    ratio = recent / prior
    mean10 = sum(closes[-10:]) / 10
    prior_mean10 = sum(closes[-11:-1]) / 10
    trend = closes[-1] > mean10 > prior_mean10
    compressed = ratio <= 0.85
    breakout = closes[-1] > float(weekly.High.iloc[-5:-1].max())
    aligned = daily_stage == "TIGHT_WATCH" and trend and compressed
    return {
        **base, "available": True,
        "status": "DAILY_WEEKLY_ALIGNED" if aligned else "NO_WEEKLY_CONFIRMATION",
        "last_complete_week": weekly.index[-1].date().isoformat(),
        "weeks_used": 12, "trend_up": trend, "range_contraction": compressed,
        "range_ratio": round(ratio, 4), "weekly_breakout": breakout,
    }
