"""Post-session audit: synthetic completed bars only, zero real credentials."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_opening_fib_shadow as shadow

OPEN = datetime(2026, 11, 16, 14, 30, tzinfo=timezone.utc)
CLOSE = OPEN + timedelta(hours=6, minutes=30)
ALERT = OPEN + timedelta(minutes=57, seconds=13)
NOW = CLOSE + timedelta(hours=9)


def marker(path: Path, session="2026-11-16", delivered_at=ALERT):
    path.write_text(json.dumps({
        "sent_session": session,
        "sent_at_utc": delivered_at.isoformat(),
    }), encoding="utf-8")


def bars(*, last=390):
    return [{"t": OPEN + timedelta(minutes=minute), "o": 100., "h": 101.,
             "l": 99., "c": 100., "v": 20000.}
            for minute in range(0, last, 5)]


def test_requires_proven_timestamp_from_actual_alert(tmp_path):
    path = tmp_path / "sent.json"
    assert shadow.read_sent_marker(path, now=NOW)[0] == "SHADOW_NO_CONFIRMED_ALERT"
    path.write_text('{"sent_session":"2026-11-16"}')
    assert shadow.read_sent_marker(path, now=NOW)[0] == "SHADOW_NO_TIMESTAMPED_ALERT"
    marker(path, session="2026-11-15")
    assert shadow.read_sent_marker(path, now=NOW)[0] == "SHADOW_INVALID_SESSION"


def test_closed_session_and_no_future_leakage(tmp_path):
    path = tmp_path / "sent.json"
    marker(path)
    assert shadow.read_sent_marker(path, now=OPEN + timedelta(hours=5))[0] == "SHADOW_WAIT_FOR_COMPLETED_SESSION"
    assert shadow.read_sent_marker(path, now=NOW)[0] == "2026-11-16"


def test_incomplete_intraday_candles_never_count_as_wins():
    good = bars()
    assert shadow._complete_future_bars(good, notice=ALERT, close=CLOSE)
    missing = [b for b in good if b["t"] != OPEN + timedelta(minutes=95)]
    assert not shadow._complete_future_bars(missing, notice=ALERT, close=CLOSE)
    duplicate = good + [good[-1]]
    assert not shadow._complete_future_bars(duplicate, notice=ALERT, close=CLOSE)


def test_replay_selection_ignores_iex_and_missing_bars():
    result = shadow.shadow_summary(["NVDA", "SPY", "BAD"], {
        "NVDA": bars(), "SPY": bars(last=385)
    }, {"NVDA": "sip", "SPY": "sip", "BAD": "iex"},
        opening=OPEN, closing=CLOSE, delivered_at=ALERT)
    assert result["complete_sip"] == 1
    assert result["outcomes"]["INCOMPLETE_BAR_COVERAGE"] == 1
    assert result["outcomes"]["SOURCE_UNAVAILABLE"] == 1
    assert result["outcomes"]["NO_TRADE"] == 1
    assert result["notice_delay_minutes"] == 58


def test_render_always_disclaims_options_and_small_samples():
    txt = shadow.render_shadow_message(
        {"scanned": 5, "complete_sip": 5,
         "outcomes": {"WIN": 1, "LOSS": 2, "EXPIRED": 1, "NO_TRADE": 1}},
        session="2026-11-16")
    assert "ليست أداء عقود خيارات" in txt
    assert "لا ننشر نسبة نجاح" in txt
    assert "تأخير SIP" in txt


def test_dry_run_requires_no_telegram_and_persists_no_quotes(tmp_path, monkeypatch):
    sent = tmp_path / "fib-sent.json"
    marker(sent)
    universe = tmp_path / "universe.txt"
    universe.write_text("SPY\n")
    monkeypatch.setenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "true")
    monkeypatch.setenv("ALPACA_PRIVATE_ALERTS_AUTHORIZED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    state = tmp_path / "shadow.json"

    class FakeProvider:
        rights_source = "alpaca_iex"
        def __init__(self, env, *, now):
            self.env = env
        def status(self):
            return "READY"
        def multi_bars(self, symbols, timeframe, start, end, *, batch):
            assert symbols == ["SPY"] and timeframe == "5m"
            return {"status": "OK", "failed_batches": 0,
                    "bars": {"SPY": bars()}, "feed": {"SPY": "sip"}}

    status = shadow.run(now=NOW, sent_marker=sent, state_path=state,
                        universe=universe, dry_run=True, provider_factory=FakeProvider)
    assert status == "SHADOW_DRY_RUN_COMPUTED"
    assert not state.exists()


def test_real_owner_private_delivery_date_only_and_dedup(tmp_path, monkeypatch):
    sent = tmp_path / "fib-sent.json"
    marker(sent)
    universe = tmp_path / "universe.txt"
    universe.write_text("SPY\n")
    state = tmp_path / "shadow.json"
    monkeypatch.setenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "true")
    monkeypatch.setenv("ALPACA_PRIVATE_ALERTS_AUTHORIZED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "654321")
    monkeypatch.delenv("TELEGRAM_OWNER_USERNAME", raising=False)
    messages = []
    monkeypatch.setattr(shadow, "owner_chat", lambda chat_id: {"type": "private"})
    monkeypatch.setattr(shadow, "send_html_message",
                        lambda text, *, chat_id: messages.append((text, chat_id)) or SimpleNamespace(message_id=123))

    class FakeProvider:
        rights_source = "alpaca_iex"
        def __init__(self, env, *, now): pass
        def status(self): return "READY"
        def multi_bars(self, *args, **kwargs):
            return {"status": "OK", "failed_batches": 0,
                    "bars": {"SPY": bars()}, "feed": {"SPY": "sip"}}

    kwargs = {"now": NOW, "sent_marker": sent, "state_path": state,
              "universe": universe, "provider_factory": FakeProvider}
    assert shadow.run(**kwargs) == "SHADOW_DELIVERED"
    assert len(messages) == 1 and messages[0][1] == "654321"
    assert json.loads(state.read_text()) == {"audited_session": "2026-11-16"}
    assert shadow.run(**kwargs) == "SHADOW_ALREADY_DELIVERED"
    assert len(messages) == 1


def test_no_rights_means_no_download_or_telegram(tmp_path, monkeypatch):
    sent = tmp_path / "fib-sent.json"
    marker(sent)
    universe = tmp_path / "universe.txt"
    universe.write_text("SPY\n")
    monkeypatch.setenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "false")
    monkeypatch.setenv("ALPACA_PRIVATE_ALERTS_AUTHORIZED", "false")

    class FakeProvider:
        rights_source = "alpaca_iex"
        def __init__(self, env, *, now): pass
        def status(self): return "DENIED_BY_POLICY"

    status = shadow.run(now=NOW, sent_marker=sent, universe=universe,
                        state_path=tmp_path / "shadow.json", provider_factory=FakeProvider)
    assert status == "SHADOW_PROVIDER_UNAVAILABLE"
