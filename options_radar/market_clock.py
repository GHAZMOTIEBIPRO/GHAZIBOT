from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import exchange_calendars as xcals
import pandas as pd


@dataclass(frozen=True)
class MarketClockState:
    checked_at: str
    session_date: str
    is_session: bool
    is_regular_open: bool
    regular_open: str | None
    regular_close: str | None


def market_clock_state(now: datetime | None = None) -> MarketClockState:
    timestamp = pd.Timestamp(now or datetime.now(timezone.utc))
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    calendar = xcals.get_calendar("XNYS")
    session_date = timestamp.tz_convert("America/New_York").date()
    session_label = pd.Timestamp(session_date)
    is_session = bool(calendar.is_session(session_label))
    is_open = bool(calendar.is_open_on_minute(timestamp, ignore_breaks=True))
    regular_open: str | None = None
    regular_close: str | None = None
    if is_session:
        schedule = calendar.schedule.loc[str(session_date):str(session_date)]
        if not schedule.empty:
            row = schedule.iloc[0]
            open_value = row.get("open")
            close_value = row.get("close")
            regular_open = None if pd.isna(open_value) else pd.Timestamp(open_value).isoformat()
            regular_close = None if pd.isna(close_value) else pd.Timestamp(close_value).isoformat()

    return MarketClockState(
        checked_at=timestamp.isoformat(),
        session_date=session_date.isoformat(),
        is_session=is_session,
        is_regular_open=is_open,
        regular_open=regular_open,
        regular_close=regular_close,
    )
