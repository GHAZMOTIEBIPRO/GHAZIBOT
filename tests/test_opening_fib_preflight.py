"""Unit-level rehearsal of owner-private preflight; never use account secrets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import run_opening_fib_daily as module


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
AUTHORIZED = {
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
    "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true",
    "TELEGRAM_BOT_TOKEN": "test",
    "TELEGRAM_OWNER_CHAT_ID": "987654",
    "TELEGRAM_CHAT_ID": "-101",
    "TELEGRAM_OWNER_USERNAME": "owner",
}


class FakeAlpaca:
    rights_source = "alpaca_iex"

    def __init__(self, env, now):
        self.env = env
        self.now = now

    def status(self):
        return "READY"

    def bars(self, symbol, interval, start, end):
        assert symbol == "SPY" and interval == "5m"
        assert (end - start) == timedelta(minutes=15)
        return {
            "status": "OK",
            "feed": "sip",
            "bars": [
                {"t": start + timedelta(minutes=5 * i)}
                for i in range(3)
            ],
        }


def _base(monkeypatch):
    for k, v in AUTHORIZED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(module, "AlpacaBars", FakeAlpaca)
    monkeypatch.setattr(module, "owner_chat",
                        lambda chat_id: {"type": "private", "username": "owner"})


def test_weekend_preflight_verifies_last_completed_session(monkeypatch):
    _base(monkeypatch)
    assert module.preflight(NOW) == "PREFLIGHT_READY"


def test_preflight_requires_private_telegram_destination(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(module, "owner_chat",
                        lambda chat_id: {"type": "supergroup", "username": "owner"})
    assert module.preflight(NOW) == "PREFLIGHT_CHAT_NOT_PRIVATE"


def test_preflight_denies_unapproved_source_use(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("ALPACA_PRIVATE_ALERTS_AUTHORIZED", "false")
    assert module.preflight(NOW) == "PREFLIGHT_RIGHTS_DENIED_TELEGRAM_PRIVATE"


def test_preflight_fails_if_owner_username_is_different(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(module, "owner_chat",
                        lambda chat_id: {"type": "private", "username": "other"})
    assert module.preflight(NOW) == "PREFLIGHT_OWNER_IDENTITY_MISMATCH"


def test_preflight_fails_closed_on_iex_only(monkeypatch):
    _base(monkeypatch)
    class IexAlpaca(FakeAlpaca):
        def bars(self, *args):
            d = super().bars(*args)
            return {**d, "feed": "iex"}
    monkeypatch.setattr(module, "AlpacaBars", IexAlpaca)
    assert module.preflight(NOW) == "PREFLIGHT_HISTORICAL_SIP_UNAVAILABLE"


def test_preflight_rejects_missing_first_5minute_bar(monkeypatch):
    _base(monkeypatch)
    class GappedAlpaca(FakeAlpaca):
        def bars(self, *args):
            d = super().bars(*args)
            return {**d, "bars": d["bars"][1:]}
    monkeypatch.setattr(module, "AlpacaBars", GappedAlpaca)
    assert module.preflight(NOW) == "PREFLIGHT_OPENING_BARS_INCOMPLETE"
