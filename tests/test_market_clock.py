from datetime import datetime, timezone

from options_radar.market_clock import market_clock_state


def test_regular_session_is_inside_extended_activity_window():
    state = market_clock_state(datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc))
    assert state.session_date == "2026-08-14"
    assert state.is_session is True
    assert state.is_regular_open is True
    assert state.is_extended_activity_open is True
    assert state.reason == "regular_session"


def test_premarket_trading_day_is_allowed_for_stock_discovery():
    state = market_clock_state(datetime(2026, 8, 14, 8, 30, tzinfo=timezone.utc))
    assert state.is_session is True
    assert state.is_regular_open is False
    assert state.is_extended_activity_open is True
    assert state.reason == "extended_activity_window"


def test_late_friday_night_new_york_is_not_active_even_if_date_is_trading_day():
    state = market_clock_state(datetime(2026, 8, 15, 2, 29, tzinfo=timezone.utc))
    assert state.session_date == "2026-08-14"
    assert state.is_session is True
    assert state.is_regular_open is False
    assert state.is_extended_activity_open is False
    assert state.reason == "outside_extended_activity_window"


def test_saturday_is_not_trading_day():
    state = market_clock_state(datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc))
    assert state.session_date == "2026-08-15"
    assert state.is_session is False
    assert state.is_regular_open is False
    assert state.is_extended_activity_open is False
    assert state.reason == "non_trading_day"
