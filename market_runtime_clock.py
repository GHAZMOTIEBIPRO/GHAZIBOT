from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketClockState:
    checked_at: str
    checked_at_new_york: str
    session_date: str
    is_session: bool
    is_regular_open: bool
    is_extended_activity_open: bool
    regular_open: str | None
    regular_close: str | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def market_clock_state(now: datetime | None = None) -> MarketClockState:
    """Return a lightweight XNYS clock without importing the trading engine package.

    Stock discovery uses 04:00-20:00 America/New_York on valid XNYS sessions so
    pre-market and after-hours remain available while late-night/weekend/holiday
    jobs fail closed. Options can use is_regular_open for regular-session gates.
    """
    timestamp = pd.Timestamp(now or datetime.now(timezone.utc))
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")

    calendar = xcals.get_calendar("XNYS")
    ny_timestamp = timestamp.tz_convert(NY_TZ)
    session_date = ny_timestamp.date()
    session_label = pd.Timestamp(session_date)
    try:
        is_session = bool(calendar.is_session(session_label))
    except Exception:
        is_session = False
    try:
        is_open = (
            bool(calendar.is_open_on_minute(timestamp.floor("min"), ignore_breaks=True))
            if is_session
            else False
        )
    except Exception:
        is_open = False

    local_clock = ny_timestamp.time().replace(tzinfo=None)
    extended_open = bool(is_session and time(4, 0) <= local_clock <= time(20, 0))

    regular_open: str | None = None
    regular_close: str | None = None
    if is_session:
        schedule = calendar.schedule.loc[str(session_date):str(session_date)]
        if not schedule.empty:
            row = schedule.iloc[0]
            open_value = row.get("open")
            close_value = row.get("close")
            regular_open = (
                None if pd.isna(open_value) else pd.Timestamp(open_value).isoformat()
            )
            regular_close = (
                None if pd.isna(close_value) else pd.Timestamp(close_value).isoformat()
            )

    if is_open:
        reason = "regular_session"
    elif extended_open:
        reason = "extended_activity_window"
    elif not is_session:
        reason = "non_trading_day"
    else:
        reason = "outside_extended_activity_window"

    return MarketClockState(
        checked_at=timestamp.isoformat(),
        checked_at_new_york=ny_timestamp.isoformat(),
        session_date=session_date.isoformat(),
        is_session=is_session,
        is_regular_open=is_open,
        is_extended_activity_open=extended_open,
        regular_open=regular_open,
        regular_close=regular_close,
        reason=reason,
    )
