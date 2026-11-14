"""Historical replay assertions use only synthetic fixture bars."""
from datetime import datetime, timedelta, timezone

from options_radar.opening_fib_replay import replay_session

OPEN = datetime(2026, 11, 16, 14, 30, tzinfo=timezone.utc)
CLOSE = OPEN + timedelta(hours=6, minutes=30)


def bar(minute, o, h, l, c, v=20000):
    return {"t": OPEN + timedelta(minutes=minute),
            "o": o, "h": h, "l": l, "c": c, "v": v}


def setup():
    return [
        bar(0, 100, 100.4, 99, 100.3),
        bar(5, 100.3, 101, 100, 100.9),
        bar(10, 100.9, 101, 99.4, 100.3),
        bar(15, 100.95, 101.15, 100.95, 101.05),
        bar(20, 101.05, 101.2, 101, 101.1),
    ]


def test_replay_requires_delayed_broadcast_then_uses_future_fill():
    bars = setup() + [bar(60, 101.16, 102.4, 101.1, 102.3)]
    report = replay_session("SPY", bars, session_open=OPEN, session_close=CLOSE)
    assert report["status"] == "WIN"
    assert report["alert_time_utc"] == (OPEN + timedelta(minutes=57)).isoformat()
    assert report["fill_time_utc"] == (OPEN + timedelta(minutes=60)).isoformat()
    assert report["research_only"] is True


def test_same_bar_target_and_stop_counts_as_loss():
    bars = setup() + [bar(60, 101.16, 102.4, 100.1, 100.4)]
    report = replay_session("SPY", bars, session_open=OPEN, session_close=CLOSE)
    assert report["status"] == "LOSS"
    assert report["net_r"] < 0


def test_price_gaps_past_target_one_do_not_count_as_good_entry():
    bars = setup() + [bar(60, 101.8, 102.1, 101.6, 101.9)]
    report = replay_session("SPY", bars, session_open=OPEN, session_close=CLOSE)
    assert report["status"] == "SKIPPED_LATE_FILL"


def test_partial_only_iex_has_no_supported_trade():
    bars = setup() + [bar(60, 101.16, 102.4, 101.1, 102.3)]
    report = replay_session("SPY", bars, session_open=OPEN,
                            session_close=CLOSE, feed="iex")
    assert report["status"] == "NO_TRADE"


def test_replay_refuses_duplicate_candles():
    bars = setup() + [setup()[0]]
    report = replay_session("SPY", bars, session_open=OPEN, session_close=CLOSE)
    assert report["status"] == "INVALID_DUPLICATE_BARS"
