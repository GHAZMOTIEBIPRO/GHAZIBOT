"""Owner onboarding: no live API calls, no account secrets, no Alpaca quotes."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from scripts import telegram_owner_setup as setup

NOW = datetime(2026, 11, 14, 11, 30, tzinfo=timezone.utc)
TEST_TOKEN = "fake_token_not_real"


def _set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TEST_TOKEN)
    monkeypatch.delenv("TELEGRAM_OWNER_USERNAME", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_CHAT_ID", raising=False)


def test_owner_id_help_responds_only_to_private_explicit_recent_command(monkeypatch, capsys):
    _set(monkeypatch)
    sent = []
    def get(token, method, *, params=None):
        assert token == TEST_TOKEN
        if method == "getWebhookInfo":
            return {"result": {"url": ""}}
        return {"result": [
            {"message": {"text": "/start", "date": int(NOW.timestamp()),
                         "chat": {"id": 333, "type": "private"},
                         "from": {"id": 333}}},
            {"message": {"text": "/ghazi_id", "date": int(NOW.timestamp()),
                         "chat": {"id": 123456, "type": "private"},
                         "from": {"id": 123456, "first_name": "غازي"}}}]}
    monkeypatch.setattr(setup, "_get", get)
    monkeypatch.setattr(setup, "send_html_message",
                        lambda text, *, chat_id: sent.append((text, chat_id)) or SimpleNamespace(message_id=5))
    assert setup.owner_id_help(now=NOW) == "OWNER_ID_REPLIED_PRIVATELY"
    assert len(sent) == 1 and sent[0][1] == "123456"
    assert "<code>123456</code>" in sent[0][0]
    assert capsys.readouterr().out == ""


def test_owner_id_help_cannot_use_webhook_polling(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(setup, "_get", lambda *args, **kwargs: {"result": {"url": "https://example.invalid/hook"}})
    assert setup.owner_id_help(now=NOW) == "OWNER_ID_WEBHOOK_ACTIVE"


def test_owner_id_help_ignores_old_group_and_empty_messages(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setattr(setup, "_get", lambda token, method, **kw:
                        {"result": {"url": ""}} if method == "getWebhookInfo" else
                        {"result": [
                            {"message": {"date": int(NOW.timestamp()), "chat": {"id": 4, "type": "private"}, "from": {"id": 4}}},
                            {"message": {"text": "/ghazi_id", "date": int(NOW.timestamp()),
                                         "chat": {"id": -100, "type": "supergroup"},
                                         "from": {"id": 22}}},
                            {"message": {"text": "/ghazi_id", "date": int(NOW.timestamp()) - 7200,
                                         "chat": {"id": 5, "type": "private"},
                                         "from": {"id": 5}}}]})
    assert setup.owner_id_help(now=NOW) == "OWNER_ID_COMMAND_NOT_FOUND"


def test_owner_id_help_restricts_to_username_when_configured(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_USERNAME", "ghazi")
    monkeypatch.setattr(setup, "_get", lambda token, method, **kw:
                        {"result": {"url": ""}} if method == "getWebhookInfo" else
                        {"result": [{"message": {
                            "text": "/ghazi_id", "date": int(NOW.timestamp()),
                            "chat": {"id": 123, "type": "private"},
                            "from": {"id": 123, "username": "other"}
                        }}]})
    assert setup.owner_id_help(now=NOW) == "OWNER_ID_COMMAND_NOT_FOUND"


def test_harmless_connectivity_message_without_market_source(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "123456")
    sent = []
    monkeypatch.setattr(setup, "_get", lambda token, method, **kw:
                        {"result": {"type": "private", "username": "ghazi"}})
    monkeypatch.setattr(setup, "send_html_message",
                        lambda text, *, chat_id: sent.append((text, chat_id)) or SimpleNamespace(message_id=9))
    assert setup.telegram_connectivity_test() == "TELEGRAM_TEST_DELIVERED"
    assert sent[0][1] == "123456"
    assert "بيانات Alpaca" in sent[0][0]
    assert "اختبار اتصال ناجح" in sent[0][0]


def test_chat_must_be_private_even_when_saved_as_owner(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "-100999")
    monkeypatch.setattr(setup, "_get", lambda *a, **kw: {"result": {"type": "channel"}})
    assert setup.telegram_connectivity_test() == "TELEGRAM_TEST_CHAT_NOT_PRIVATE"


def test_unconfigured_owner_blocks_test(monkeypatch):
    _set(monkeypatch)
    assert setup.telegram_connectivity_test() == "TELEGRAM_TEST_OWNER_CHAT_NOT_SET"


def test_username_mismatch_blocks_test(monkeypatch):
    _set(monkeypatch)
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "123456")
    monkeypatch.setenv("TELEGRAM_OWNER_USERNAME", "ghazi")
    monkeypatch.setattr(setup, "_get", lambda *a, **kw: {"result": {"type": "private", "username": "someone_else"}})
    assert setup.telegram_connectivity_test() == "TELEGRAM_TEST_OWNER_IDENTITY_MISMATCH"
