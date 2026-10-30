"""Real user watchlist bot diagnostics: no invented prices and no duplicate sends."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_radar.focus_universe import FOCUS_STOCKS
from scripts import send_focus_bot_status as bot
from scripts import send_classical_direction_alerts as classical
from scripts import send_strict_options_alerts as strict
from scripts import send_omega_watch_alerts as omega


NOW = datetime(2026, 10, 30, 15, 15, tzinfo=timezone.utc)


def reports(now=NOW):
    stamp = (now - timedelta(minutes=2)).isoformat()
    health = {"generated_at": stamp, "status": "degraded",
              "checks": {"option_quotes_production_ready": None}}
    sources = {"generated_at": stamp, "row_counts": {"stocks": 0, "options": 0},
               "coverage_diagnostics": {"options_execution_quote_ready": False,
                                        "options_trade_flow_ready": False,
                                        "blocking_codes": ["NO_EXECUTION_GRADE_OPTION_QUOTE"]}}
    index = {"generated_at": stamp, "status": "SOURCE_TERMS_BLOCKED"}
    guardian = {"generated_at": stamp, "active_count": 0}
    return health, sources, index, guardian


def test_weekday_daily_status_one_telegram_receipt_only():
    state = {}
    messages = []
    def recorder(msg):
        messages.append(msg)
        return SimpleNamespace(message_id=123)
    inputs = reports()
    assert bot.run(*inputs, state, now=NOW, send=recorder) == "TELEGRAM_ACCEPTED"
    assert bot.run(*inputs, state, now=NOW + timedelta(minutes=3), send=recorder) == "NOT_DUE"
    assert len(messages) == 1
    assert "SPX" in messages[0] and "NDX" in messages[0]
    assert "AMD" in messages[0] and "BABA" in messages[0]
    assert "غير مؤهلة للتنفيذ" in messages[0]
    assert "لا توجد توصية دخول" in messages[0]
    assert state["last_message_id"] == 123
    assert state["last_sent_day"] == "2026-10-30"


def test_bot_not_due_before_evening_or_weekends():
    assert not bot.due(datetime(2026, 10, 30, 10, tzinfo=timezone.utc), {})
    assert not bot.due(datetime(2026, 10, 31, 18, tzinfo=timezone.utc), {})
    assert bot.due(NOW, {})


def test_stale_missing_source_fail_closed_even_if_old_report_says_ready():
    health, sources, index, guardian = reports()
    sources["generated_at"] = (NOW - timedelta(days=1)).isoformat()
    sources["coverage_diagnostics"]["options_execution_quote_ready"] = True
    health["checks"]["option_quotes_production_ready"] = True
    index["generated_at"] = "2026-10-27T12:00:00+00:00"
    result = bot.summarize(health, sources, index, guardian, now=NOW)
    assert result["production_option_quotes_verified"] is False
    assert result["index_data_blocked"] is True
    assert result["public_option_rows"] is None
    assert result["decision_authority"] is False


def test_success_needs_telegram_api_receipt_and_no_fake_ack():
    state = {}
    with pytest.raises(RuntimeError, match="message_id"):
        bot.run(*reports(), state, now=NOW,
                send=lambda _: SimpleNamespace(message_id=None))
    assert state == {}


def test_telegram_status_escapes_provider_supplied_health_field():
    health, sources, index, guardian = reports()
    health["status"] = '<script>alert("oops")</script>'
    msg = bot.message(bot.summarize(health, sources, index, guardian, now=NOW), now=NOW)
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_core_stocks_include_all_requested_and_rendering_is_wired():
    assert len(set(FOCUS_STOCKS)) == 9
    assert all(symbol in bot.message(bot.summarize(*reports(), now=NOW), now=NOW)
               for symbol in FOCUS_STOCKS)
    import inspect
    assert "FOCUS_STOCKS" in inspect.getsource(classical.send)
    assert "FOCUS_OPTIONABLE" in inspect.getsource(strict.send)
    assert "FOCUS_OPTIONABLE" in inspect.getsource(omega._rows)
    text = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert "python -m scripts.send_focus_bot_status" in text
    assert "github.event_name != 'push'" in text
    vault = Path("scripts/runtime_state_vault.py").read_text(encoding="utf-8")
    assert '"data/live/focus_bot_status_state.json"' in vault
