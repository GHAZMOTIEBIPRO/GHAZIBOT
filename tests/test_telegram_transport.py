from __future__ import annotations

from pathlib import Path

import pytest
import requests

from options_radar import telegram_transport as transport


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "result": {"message_id": 42}}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_send_success_returns_message_id(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(payload={"ok": True, "result": {"message_id": 77}})

    monkeypatch.setattr(transport.requests, "post", fake_post)
    result = transport.send_html_message("hello", token="token", chat_id="chat")
    assert result.message_id == 77
    assert result.attempts == 1
    assert len(calls) == 1


def test_429_honors_retry_after_then_succeeds(monkeypatch):
    responses = [
        FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 2}}),
        FakeResponse(payload={"ok": True, "result": {"message_id": 9}}),
    ]
    sleeps = []
    monkeypatch.setattr(transport.requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = transport.send_html_message("rate limited", token="token", chat_id="chat")
    assert result.attempts == 2
    assert result.message_id == 9
    assert sleeps == [2.0]


def test_503_retries_with_bounded_backoff(monkeypatch):
    responses = [
        FakeResponse(status_code=503, payload={"ok": False}),
        FakeResponse(payload={"ok": True, "result": {"message_id": 10}}),
    ]
    sleeps = []
    monkeypatch.setattr(transport.requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(transport.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = transport.send_html_message("temporary server issue", token="token", chat_id="chat")
    assert result.attempts == 2
    assert sleeps == [0.8]


def test_non_retryable_400_fails_immediately(monkeypatch):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(status_code=400, payload={"ok": False})

    monkeypatch.setattr(transport.requests, "post", fake_post)
    with pytest.raises(requests.HTTPError):
        transport.send_html_message("bad request", token="token", chat_id="chat")
    assert calls == 1


@pytest.mark.parametrize("exc", [requests.Timeout("timeout"), requests.ConnectionError("disconnect")])
def test_ambiguous_transport_failure_is_not_retried(monkeypatch, exc):
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise exc

    monkeypatch.setattr(transport.requests, "post", fake_post)
    with pytest.raises(type(exc)):
        transport.send_html_message("do not duplicate", token="token", chat_id="chat")
    assert calls == 1


def test_message_over_telegram_limit_is_blocked_before_network(monkeypatch):
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse()

    monkeypatch.setattr(transport.requests, "post", fake_post)
    with pytest.raises(ValueError, match="4096"):
        transport.send_html_message("x" * 4097, token="token", chat_id="chat")
    assert called is False


def test_missing_destination_fails_closed(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(RuntimeError, match="not ready"):
        transport.send_html_message("hello", token="", chat_id="")


def test_verify_bot_success(monkeypatch):
    monkeypatch.setattr(
        transport.requests,
        "get",
        lambda *a, **k: FakeResponse(payload={"ok": True, "result": {"id": 123, "username": "omega_bot"}}),
    )
    result = transport.verify_bot(token="token")
    assert result == {"ok": True, "bot_id": 123, "username": "omega_bot"}


def test_verify_bot_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        transport.requests,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("timeout")),
    )
    result = transport.verify_bot(token="token")
    assert result["ok"] is False
    assert result["reason"] == "Timeout"


def test_bootstrap_masks_destination_before_export(monkeypatch, tmp_path, capsys):
    from scripts import telegram_connection_bootstrap as bootstrap

    destination = "private-destination"
    env_file = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    connection = tmp_path / "connection.json"
    connection.write_text('{"chat_id":"private-destination"}', encoding="utf-8")
    assert bootstrap.bootstrap(connection) == 0

    output = capsys.readouterr().out.splitlines()
    assert f"::add-mask::{destination}" in output
    assert f"TELEGRAM_CHAT_ID={destination}" in env_file.read_text(encoding="utf-8")


def test_notifier_workflows_do_not_upload_connection_every_run():
    root = Path(__file__).resolve().parents[1]
    for name in (
        "stock-telegram-alerts.yml",
        "options-telegram-alerts.yml",
        "classical-direction-radar.yml",
        "cross-confirmation.yml",
        "radar-health.yml",
    ):
        text = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "Upload encrypted Telegram destination" not in text
        assert "telegram-connection-keeper.yml" in text

    keeper = (root / ".github" / "workflows" / "telegram-connection-keeper.yml").read_text(encoding="utf-8")
    assert "Upload one centralized Telegram destination" in keeper
    assert "verify_bot" in keeper
