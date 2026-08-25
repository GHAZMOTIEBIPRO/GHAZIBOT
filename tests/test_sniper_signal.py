from datetime import datetime, timezone

import pytest

from scripts.sniper_signal import format_sniper_message, parse_sniper_event


def _payload(**overrides):
    data = {
        "schema": "sniper.v1",
        "source": "سنايبر",
        "symbol": "NVDA",
        "ticker_id": "NASDAQ:NVDA",
        "direction": "CALL",
        "score": 88,
        "grade": "A",
        "horizon": "يومي",
        "timeframe": "5",
        "entry": 182.1,
        "stop": 180.5,
        "target_1": 185.0,
        "target_2": 188.0,
        "reward_risk": 1.8,
        "engine": "انعكاس",
        "regime": "اتجاه صاعد",
        "event_time_ms": 1787623200000,
    }
    data.update(overrides)
    return data


def test_parse_and_format():
    now = datetime.fromtimestamp(1787623200, tz=timezone.utc)
    event = parse_sniper_event(_payload(), now=now)
    assert event.symbol == "NVDA"
    assert event.direction == "CALL"
    assert event.horizon == "يومي"
    text = format_sniper_message(event)
    assert "سنايبر" in text
    assert "NVDA" in text
    assert "كول" in text
    assert "88/100" in text


def test_rejects_wrong_source():
    now = datetime.fromtimestamp(1787623200, tz=timezone.utc)
    with pytest.raises(ValueError):
        parse_sniper_event(_payload(source="other"), now=now)


def test_rejects_stale_event(monkeypatch):
    monkeypatch.setenv("SNIPER_MAX_EVENT_AGE_SECONDS", "60")
    now = datetime.fromtimestamp(1787626800, tz=timezone.utc)
    with pytest.raises(ValueError, match="stale"):
        parse_sniper_event(_payload(), now=now)


def test_arabic_put_direction():
    now = datetime.fromtimestamp(1787623200, tz=timezone.utc)
    event = parse_sniper_event(_payload(direction="بوت"), now=now)
    assert event.direction == "PUT"
