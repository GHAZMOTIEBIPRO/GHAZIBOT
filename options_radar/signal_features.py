"""Point-in-time feature snapshot frozen when a stock signal is first recorded.

Only values present on the signal row at that moment are copied; nothing is
recomputed later, so a later evaluation cannot leak future information.
Missing inputs stay None. The snapshot has no decision authority: it exists
so stage rules can be tested on time-separated data before any change.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import exchange_calendars as xcals
import pandas as pd

VERSION = "ENTRY_FEATURES_V1"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def session_phase(now: datetime) -> str:
    """PRE_MARKET / REGULAR / AFTER_HOURS on an XNYS session day, else CLOSED."""
    try:
        calendar = xcals.get_calendar("XNYS")
        stamp = pd.Timestamp(now).tz_convert("America/New_York")
        day = stamp.date()
        if not calendar.is_session(day):
            return "CLOSED"
        opened = calendar.session_open(day)
        closed = calendar.session_close(day)
    except (ValueError, KeyError, TypeError):
        return "UNKNOWN"
    moment = pd.Timestamp(now)
    if moment < opened:
        return "PRE_MARKET"
    if moment < closed:
        return "REGULAR"
    return "AFTER_HOURS"


def _catalyst_age_minutes(row: dict[str, Any], now: datetime) -> float | None:
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    published = _parse(cause.get("published_at") or cause.get("filed_at") or cause.get("event_at"))
    if published is None or published > now:
        return None  # a future or unknown timestamp is not evidence of freshness
    return round((now - published).total_seconds() / 60.0, 1)


def entry_features(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    memory = row.get("institutional_memory") if isinstance(row.get("institutional_memory"), dict) else {}
    dimensions = row.get("explosion_dimensions") if isinstance(row.get("explosion_dimensions"), dict) else {}
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    price = _first(row, "price")
    volume = _first(row, "volume")
    dollar_volume = _first(row, "dollar_volume")
    if dollar_volume is None and price is not None and volume is not None:
        dollar_volume = round(price * volume, 2)
    return {
        "version": VERSION,
        "frozen_at": now.isoformat(),
        "session_phase": session_phase(now),
        "volume": {
            "relative_volume_full_day_basis": _first(row, "relative_volume", "rvol"),
            "volume": volume,
            "turnover_pct": _first(row, "turnover_pct"),
            "acceleration_score": _num(memory.get("acceleration")),
            "participation_score": _num(dimensions.get("participation")),
        },
        "float": {
            "float_shares": _first(row, "float_shares"),
            "shares_outstanding": _first(row, "shares_outstanding"),
            "supply_score": _first(row, "supply_score"),
        },
        "catalyst": {
            "category": str(cause.get("category") or row.get("catalyst_form") or "") or None,
            "official": cause.get("official_confirmed") is True,
            "score": _first(row, "catalyst_score"),
            "age_minutes": _catalyst_age_minutes(row, now),
        },
        "relative_strength": {
            "move_pct": _first(row, "move_pct", "day_move_pct"),
            "sector_vs_market": _first(row, "sector_vs_market"),
            "sector_score": _first(row, "sector_score"),
            "rsi": _first(row, "rsi"),
        },
        "premarket": {
            "gap_pct": _first(row, "gap_pct"),
            "premarket_move_pct": _first(row, "premarket_move_pct", "premarket_change_pct"),
        },
        "liquidity": {
            "price": price,
            "dollar_volume": dollar_volume,
            "avg_dollar_volume": _first(row, "avg_dollar_volume"),
            "market_cap": _first(row, "market_cap"),
        },
        "dilution": {"risk": _first(row, "dilution_risk")},
        "market_regime": str(row.get("market_regime") or "") or None,
        "earlyness": _num(memory.get("earlyness")),
        "decision_authority": False,
    }
