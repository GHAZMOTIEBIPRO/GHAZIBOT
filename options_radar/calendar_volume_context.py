"""Independent, optional expiry/weekday normalization for historic option volume.

Research context only. Different expiries, dates and weekdays must not be
compared as if they were an identical market session. Not a trading signal,
proof of opening trades, or evidence of a dealer's inventory.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd


def _date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tz is None:
        return None
    return parsed.tz_convert("America/New_York").date()


def _expiration_date(value: Any) -> date | None:
    # An expiry is a calendar date, not a provider event timestamp.
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date() if value.tz is None else value.tz_convert("America/New_York").date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return _date(value)


def calendar_adjusted_contract_volume(
    current_volume: Any,
    history: pd.DataFrame | None,
    *,
    observed_at: Any,
    expiration: Any,
    minimum_joint_sessions: int = 3,
    max_prior_sessions: int = 90,
) -> dict[str, Any]:
    """Compare with *prior same-weekday, same-DTE-band* contract sessions.

    Never assumes the analysis process clock is a provider event timestamp.
    Expiry-band coverage is important: a 0DTE expiry Friday is not comparable
    with a prior Friday when that same contract had 7+ days to expiration.
    """
    base: dict[str, Any] = {
        "available": False,
        "reason": "INSUFFICIENT_EVIDENCE",
        "ratio": None,
        "historical_median": None,
        "joint_observations": 0,
        "research_only": True,
        "score_adjustment": 0.0,
        "decision_authority": False,
        "expiry_normalized": False,
        "source_event_time_required": True,
    }
    observed = _date(observed_at)
    expiry = _expiration_date(expiration)
    if observed is None or expiry is None:
        return {**base, "reason": "MISSING_DATED_PROVENANCE"}
    dte = (expiry - observed).days
    if dte < 0:
        return {**base, "reason": "EXPIRED_CONTRACT"}
    if isinstance(current_volume, bool):
        return {**base, "reason": "INVALID_VOLUME"}
    try:
        volume = float(current_volume)
    except (TypeError, ValueError, OverflowError):
        return {**base, "reason": "INVALID_VOLUME"}
    if not math.isfinite(volume) or volume < 0:
        return {**base, "reason": "INVALID_VOLUME"}
    if (history is None or history.empty or not isinstance(history.index, pd.DatetimeIndex)
            or not history.index.tz or not 1 <= minimum_joint_sessions <= 30
            or not 5 <= max_prior_sessions <= 365):
        return {**base, "reason": "MISSING_DATED_HISTORY"}
    column = "Volume" if "Volume" in history else "volume" if "volume" in history else None
    if column is None:
        return {**base, "reason": "MISSING_VOLUME_COLUMN"}

    def band(days: int) -> str:
        if days <= 1:
            return "DTE_0_1"
        if days <= 7:
            return "DTE_2_7"
        if days <= 30:
            return "DTE_8_30"
        return "DTE_31_PLUS"

    required = band(dte)
    prior = history.sort_index().tail(max_prior_sessions)
    prices: list[float] = []
    dates: set[date] = set()
    for when, val in zip(prior.index, prior[column], strict=False):
        trading_date = when.tz_convert("America/New_York").date()
        if trading_date >= observed or trading_date in dates:
            continue
        historical_dte = (expiry - trading_date).days
        if (historical_dte < 0 or band(historical_dte) != required
                or trading_date.weekday() != observed.weekday()):
            continue
        if isinstance(val, bool):
            continue
        try:
            number = float(val)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number) and number >= 0:
            prices.append(number)
            dates.add(trading_date)
    if len(prices) < minimum_joint_sessions:
        return {**base, "reason": "INSUFFICIENT_MATCHED_HISTORY",
                "joint_observations": len(prices), "dte_band": required}
    baseline = float(pd.Series(prices).median())
    if baseline <= 0:
        return {**base, "reason": "ZERO_BASELINE",
                "joint_observations": len(prices), "dte_band": required}
    return {
        **base,
        "available": True,
        "reason": "OK",
        "ratio": round(volume / baseline, 4),
        "historical_median": round(baseline, 4),
        "joint_observations": len(prices),
        "dte_band": required,
        "expiry_normalized": True,
        "observation_day_et": observed.isoformat(),
        "expiry": expiry.isoformat(),
    }
