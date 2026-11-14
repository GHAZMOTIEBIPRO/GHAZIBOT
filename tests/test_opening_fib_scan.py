from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.opening_fib_scan import evaluate, render_private_digest

UTC = timezone.utc
OPEN = datetime(2026, 11, 16, 14, 30, tzinfo=UTC)  # 09:30 NY / EST
NOW = datetime(2026, 11, 16, 15, 20, tzinfo=UTC)


def candle(minute, o, h, l, c, v=1000):
    return {"t": OPEN + timedelta(minutes=minute), "o": o, "h": h,
            "l": l, "c": c, "v": v}


def opening():
    return [
        candle(0, 100, 100.4, 99, 100.3),
        candle(5, 100.3, 101, 100, 100.9),
        candle(10, 100.9, 101, 99.4, 100.3),
    ]


def up():
    return opening() + [
        candle(15, 100.95, 101.15, 100.95, 101.05),
        candle(20, 101.05, 101.2, 101.0, 101.1),
    ]


def down():
    return opening() + [
        candle(15, 99, 99.05, 98.80, 98.95),
        candle(20, 98.95, 99, 98.75, 98.9),
    ]


def test_call_after_two_consecutive_confirmations():
    result = evaluate("SPY", up(), session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "WATCH_CALL"
    assert result["opening_high"] == 101
    assert result["opening_low"] == 99
    assert result["midpoint"] == 100
    assert result["targets"] == [101.544, 102.236, 103]
    assert result["trigger"] == 101
    assert result["entry_observed_delayed"] == 101.1
    assert result["rr2"] >= 1.5


def test_put_uses_downward_extensions():
    result = evaluate("QQQ", down(), session_open=OPEN, now=NOW, feed="sip")
    assert result["state"] == "WATCH_PUT"
    assert result["trigger"] == 99
    assert result["targets"] == [98.456, 97.764, 97]
    assert result["stop"] == 99.5


def test_missing_one_of_three_opening_candles_is_no_data():
    b = up()
    del b[1]
    result = evaluate("NVDA", b, session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "NO_DATA"


def test_unfinished_provider_delay_cannot_signal():
    result = evaluate("SPY", up(), session_open=OPEN,
                      now=OPEN + timedelta(minutes=19), feed="iex")
    assert result["state"] == "NO_DATA"


def test_unrecognized_feed_refuses_price():
    result = evaluate("SPY", up(), session_open=OPEN, now=NOW, feed="unknown")
    assert result["state"] == "NO_DATA"


def test_repeated_bar_refused():
    result = evaluate("SPY", up() + [up()[0]],
                      session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "NO_DATA"


def test_wait_when_no_close_breakout():
    b = opening() + [
        candle(15, 100, 100.4, 99.8, 100.1),
        candle(20, 100.1, 100.5, 100, 100.4),
    ]
    result = evaluate("SPY", b, session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "WAIT"


def test_gap_cannot_confirm():
    b = opening() + [
        candle(15, 100.95, 101.15, 100.95, 101.05),
        candle(25, 101.05, 101.2, 101, 101.1),
    ]
    result = evaluate("SPY", b, session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "WAIT"


def test_stale_confirmation_rejected():
    result = evaluate("SPY", up(), session_open=OPEN,
                      now=OPEN + timedelta(minutes=120), feed="iex")
    assert result["state"] == "WAIT"


def test_unrealistic_narrow_opening_waits():
    b = [
        candle(0, 100, 100.01, 100, 100.01),
        candle(5, 100.01, 100.02, 100.01, 100.02),
        candle(10, 100.02, 100.025, 100.01, 100.02),
    ]
    result = evaluate("SPY", b, session_open=OPEN, now=NOW, feed="iex")
    assert result["state"] == "WAIT"


def test_digest_marks_delayed_data_and_no_fake_option_quote():
    result = evaluate("SPY", up(), session_open=OPEN, now=NOW, feed="iex")
    message = render_private_digest([result, {"symbol": "AMD", "state": "NO_DATA"}],
                                    session_date="2026-11-16")
    assert "16 دقيقة" in message
    assert "مراقبة كول" in message
    assert "SPY" in message and "AMD" in message
    assert "عقود خيارات" in message
    assert len(message) <= 3900
