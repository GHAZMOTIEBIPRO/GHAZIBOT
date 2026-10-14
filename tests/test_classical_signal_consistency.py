from datetime import datetime, timezone

from scripts.send_classical_direction_alerts import _consistent_signal, _fresh_session_bar, send


def _row():
    return {"symbol": "MU", "decision": "CALL", "price": 100.0, "invalidation_level": 98.0, "daily": {"direction": "BULLISH"}, "hourly": {"direction": "BULLISH"}, "intraday": {"direction": "BULLISH", "close": 100.0}}


def test_valid_call():
    assert _consistent_signal(_row())


def test_broken_support():
    row = _row()
    row["invalidation_level"] = 101.0
    assert not _consistent_signal(row)


def test_conflicting_intraday():
    row = _row()
    row["intraday"]["direction"] = "BEARISH"
    assert not _consistent_signal(row)


def test_mismatched_price():
    row = _row()
    row["intraday"]["close"] = 95.0
    assert not _consistent_signal(row)


def test_missing_invalidation():
    row = _row()
    del row["invalidation_level"]
    assert not _consistent_signal(row)


def test_valid_put():
    row = _row()
    row.update(decision="PUT", invalidation_level=102.0)
    for key in ("daily", "hourly", "intraday"):
        row[key]["direction"] = "BEARISH"
    assert _consistent_signal(row)


# 14 October 2026, 10:00 AM New York (EDT) is a regular NYSE session.
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)


def test_fresh_15m_bar_is_eligible_during_nyse_hours():
    row = _row()
    row["intraday_bar_closed_at"] = "2026-10-14T13:45:00+00:00"
    assert _fresh_session_bar(row, now=NOW)


def test_yesterday_bar_cannot_be_sent_during_today_session():
    row = _row()
    row["intraday_bar_closed_at"] = "2026-10-13T19:45:00+00:00"
    assert not _fresh_session_bar(row, now=NOW)


def test_missing_or_naive_timestamp_fails_closed():
    row = _row()
    assert not _fresh_session_bar(row, now=NOW)
    row["intraday_bar_closed_at"] = "2026-10-14T13:45:00"
    assert not _fresh_session_bar(row, now=NOW)


def test_future_and_older_intraday_bars_fail_closed():
    row = _row()
    row["intraday_bar_closed_at"] = "2026-10-14T14:15:00Z"
    assert not _fresh_session_bar(row, now=NOW)
    row["intraday_bar_closed_at"] = "2026-10-14T13:00:00Z"
    assert not _fresh_session_bar(row, now=NOW)


def test_closed_market_and_holiday_do_not_send():
    row = _row()
    row["intraday_bar_closed_at"] = "2026-10-14T13:45:00Z"
    assert not _fresh_session_bar(row, now=datetime(2026, 10, 14, 21, tzinfo=timezone.utc))
    row["intraday_bar_closed_at"] = "2026-12-25T14:45:00Z"
    assert not _fresh_session_bar(row, now=datetime(2026, 12, 25, 15, tzinfo=timezone.utc))


def test_sender_rejects_old_telegram_payload_even_with_bullish_frames(monkeypatch):
    import scripts.send_classical_direction_alerts as sender
    events = []
    monkeypatch.setattr(sender, "_send", events.append)
    monkeypatch.setattr(sender, "_fresh_session_bar", lambda row: False)
    state = {"sent": {}}
    assert send({"path": "classical_direction", "signals": [_row()]}, state) == 0
    assert state["blocked_invalid_or_stale"] == 1
    assert events == []
