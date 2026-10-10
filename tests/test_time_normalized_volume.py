from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from options_radar.time_normalized_volume import time_normalized_rvol

NY = ZoneInfo("America/New_York")


def _bars(*, current_multiplier: float = 2.0) -> pd.DataFrame:
    rows = []
    volumes = []
    session_days = [
        datetime(2026, 9, 21, 9, 30, tzinfo=NY),
        datetime(2026, 9, 22, 9, 30, tzinfo=NY),
        datetime(2026, 9, 23, 9, 30, tzinfo=NY),
        datetime(2026, 9, 24, 9, 30, tzinfo=NY),
        datetime(2026, 9, 25, 9, 30, tzinfo=NY),
        datetime(2026, 9, 28, 9, 30, tzinfo=NY),
        datetime(2026, 9, 29, 9, 30, tzinfo=NY),
        datetime(2026, 9, 30, 9, 30, tzinfo=NY),
        datetime(2026, 10, 1, 9, 30, tzinfo=NY),
        datetime(2026, 10, 2, 9, 30, tzinfo=NY),
    ]
    for day in session_days:
        for minutes in (0, 5, 10, 15, 20, 25, 30):
            rows.append((day + timedelta(minutes=minutes)).astimezone(timezone.utc))
            volumes.append(1_000.0)

    current = datetime(2026, 10, 5, 9, 30, tzinfo=NY)
    for minutes in (0, 5, 10, 15, 20, 25, 30):
        rows.append((current + timedelta(minutes=minutes)).astimezone(timezone.utc))
        volumes.append(1_000.0 * current_multiplier)

    return pd.DataFrame(
        {
            "Open": 10.0,
            "High": 10.2,
            "Low": 9.8,
            "Close": 10.0,
            "Volume": volumes,
        },
        index=pd.DatetimeIndex(rows),
    )


def test_same_clock_rvol_compares_only_volume_available_by_current_minute():
    now = datetime(2026, 10, 5, 9, 50, tzinfo=NY)
    result = time_normalized_rvol(_bars(current_multiplier=2.0), now=now)

    assert result.available is True
    assert result.ratio == 2.0
    assert result.sample_sessions == 10
    assert result.current_cumulative_volume == 8_000.0
    assert result.historical_median_cumulative_volume == 4_000.0
    assert result.cutoff_clock_et == "09:45"
    assert result.research_only is True
    assert result.live_score_adjustment is False
    assert result.decision_authority is False


def test_future_current_session_bars_do_not_leak_into_same_clock_rvol():
    now = datetime(2026, 10, 5, 9, 40, tzinfo=NY)
    frame = _bars(current_multiplier=2.0)
    # Add enormous future bars after the 09:40 cutoff. They must not change ratio.
    for minute in (45, 50, 55):
        stamp = datetime(2026, 10, 5, 9, minute, tzinfo=NY).astimezone(timezone.utc)
        frame.loc[stamp, ["Open", "High", "Low", "Close", "Volume"]] = [
            10,
            10.2,
            9.8,
            10,
            10_000_000,
        ]

    result = time_normalized_rvol(frame, now=now)

    assert result.available is True
    assert result.ratio == 2.0
    assert result.current_cumulative_volume == 4_000.0
    assert result.historical_median_cumulative_volume == 2_000.0


def test_current_session_is_excluded_from_historical_baseline():
    now = datetime(2026, 10, 5, 10, 0, tzinfo=NY)
    result = time_normalized_rvol(_bars(current_multiplier=8.0), now=now)

    assert result.available is True
    assert result.ratio == 8.0
    assert result.historical_median_cumulative_volume == 6_000.0


def test_premarket_fails_closed_without_extended_hours_history():
    now = datetime(2026, 10, 5, 8, 30, tzinfo=NY)
    result = time_normalized_rvol(_bars(), now=now)

    assert result.available is False
    assert result.ratio is None
    assert result.reason == "premarket_not_comparable_to_regular_session_profile"


def test_insufficient_historical_sessions_is_unavailable():
    frame = _bars().loc["2026-10-01":]
    now = datetime(2026, 10, 5, 9, 50, tzinfo=NY)
    result = time_normalized_rvol(frame, now=now)

    assert result.available is False
    assert result.reason == "insufficient_comparable_sessions"

def test_duplicate_bar_timestamp_does_not_double_count_volume():
    now = datetime(2026, 10, 5, 9, 50, tzinfo=NY)
    frame = _bars(current_multiplier=2.0)
    duplicate_stamp = datetime(2026, 10, 5, 9, 35, tzinfo=NY).astimezone(timezone.utc)
    duplicate = frame.loc[[duplicate_stamp]].copy()
    duplicate["Volume"] = 2_000.0
    frame = pd.concat([frame, duplicate]).sort_index()

    result = time_normalized_rvol(frame, now=now)

    assert result.available is True
    assert result.ratio == 2.0


def test_stale_current_session_profile_fails_closed():
    now = datetime(2026, 10, 5, 10, 0, tzinfo=NY)
    frame = _bars(current_multiplier=2.0)
    cutoff = datetime(2026, 10, 5, 9, 40, tzinfo=NY).astimezone(timezone.utc)
    frame = frame[
        (frame.index.date != now.date())
        | (frame.index <= cutoff)
    ]

    result = time_normalized_rvol(frame, now=now, maximum_current_lag_minutes=10)

    assert result.available is False
    assert result.reason == "current_session_profile_too_stale_or_sparse"
    assert result.current_bar_lag_minutes > 10
    assert result.profile_quality == "STALE_OR_SPARSE"


def test_1600_extended_bar_is_never_counted_as_regular_session_volume():
    frame = _bars(current_multiplier=2.0)
    stamp = datetime(2026, 10, 5, 16, 0, tzinfo=NY).astimezone(timezone.utc)
    frame.loc[stamp, ["Open", "High", "Low", "Close", "Volume"]] = [
        10,
        10.2,
        9.8,
        10,
        99_000_000,
    ]

    result = time_normalized_rvol(
        frame,
        now=datetime(2026, 10, 5, 16, 10, tzinfo=NY),
        maximum_current_lag_minutes=400,
    )

    assert result.cutoff_clock_et == "15:55"
    assert result.current_cumulative_volume < 99_000_000


def test_profile_reports_bar_coverage_and_freshness():
    result = time_normalized_rvol(
        _bars(current_multiplier=2.0),
        now=datetime(2026, 10, 5, 9, 50, tzinfo=NY),
    )

    assert result.latest_current_bar_clock_et == "09:45"
    assert result.current_bar_lag_minutes == 0
    assert result.expected_completed_slots == 4
    assert result.observed_current_slots == 4
    assert result.current_slot_coverage_pct == 100.0
    assert result.profile_quality == "GOOD"

