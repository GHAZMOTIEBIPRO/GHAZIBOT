"""Telegram diagnosis: never leaks a value, finds the credential's scope, sends at most once."""
from __future__ import annotations

import json

from scripts import telegram_diagnose as diag

TOKEN = "123456789:AAH" + "x" * 32
GROUP = "-1001234567890"


class FakeTelegram:
    """Records calls; answers like the Bot API."""

    def __init__(self, *, token_ok=True, chat_ok=True, status="administrator", chat_type="supergroup", send_ok=True):
        self.calls = []
        self.token_ok, self.chat_ok, self.status = token_ok, chat_ok, status
        self.chat_type, self.send_ok = chat_type, send_ok
        self.token = TOKEN

    def call(self, method, **params):
        self.calls.append(method)
        if not self.token_ok:
            return {"ok": False, "http_status": 401, "error_code": 401, "description": "Unauthorized"}
        if method == "getMe":
            return {"ok": True, "http_status": 200, "result": {"id": 42, "username": "ghazi_bot", "is_bot": True}}
        if method == "getWebhookInfo":
            return {"ok": True, "result": {"url": ""}}
        if method == "getChat":
            if not self.chat_ok:
                return {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
            return {"ok": True, "result": {"id": int(GROUP), "type": self.chat_type, "title": "private name"}}
        if method == "getChatMember":
            return {"ok": True, "result": {"status": self.status, "can_post_messages": True}}
        if method == "getUpdates":
            return {"ok": True, "result": [{"my_chat_member": {"chat": {"id": int(GROUP), "type": "supergroup"}}}]}
        if method == "sendMessage":
            assert params["chat_id"] == GROUP
            return ({"ok": True, "http_status": 200, "result": {"message_id": 777, "date": 1}}
                    if self.send_ok else {"ok": False, "http_status": 403, "error_code": 403,
                                          "description": "Forbidden: bot was kicked"})
        raise AssertionError(method)


def env(**kw):
    base = {"GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "9"}
    base.update(kw)
    return base


def test_describe_never_returns_the_value_and_flags_damage():
    info = diag.describe(f'  "{TOKEN}"\n', "token")
    assert info["present"] and info["surrounding_whitespace"] and info["surrounding_quotes"]
    assert info["shape_ok_as_stored"] is False and info["shape_ok_after_trim"] is True
    assert TOKEN not in json.dumps(info) and "AAH" not in json.dumps(info)
    assert diag.describe("", "token") == {"present": False}


def test_inventory_finds_a_token_saved_under_another_name_or_as_a_variable():
    found = diag.inventory(env(DIAG_SECRET_TG_BOT_TOKEN=TOKEN, DIAG_VAR_TELEGRAM_CHAT_ID=GROUP))
    assert set(found) == {"secrets.TG_BOT_TOKEN", "vars.TELEGRAM_CHAT_ID"}
    token, source = diag.choose(env(DIAG_SECRET_TG_BOT_TOKEN=TOKEN, DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN), "token")
    assert token == TOKEN and source == "secrets.TELEGRAM_BOT_TOKEN"   # canonical name wins


def test_no_token_in_scope_is_reported_not_crashed():
    out = diag.run(env(), send=True)
    assert out["verdict"] == "NO_TOKEN_IN_THIS_SCOPE" and out["found"] == {}


def test_full_path_sends_exactly_one_message_and_reports_message_id():
    tg = FakeTelegram()
    out = diag.run(env(DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN, DIAG_SECRET_TELEGRAM_CHAT_ID=GROUP), send=True,
                   telegram=tg)
    assert out["verdict"] == "DELIVERED" and out["test_message"]["message_id"] == 777
    assert tg.calls.count("sendMessage") == 1
    text = json.dumps(out, ensure_ascii=False)
    assert TOKEN not in text and GROUP not in text and "private name" not in text
    assert out["chat"]["chat"] == "…7890" and out["canonical_names_used"] is True


def test_rerun_attempt_never_sends_again():
    tg = FakeTelegram()
    out = diag.run(env(GITHUB_RUN_ATTEMPT="2", DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN,
                       DIAG_SECRET_TELEGRAM_CHAT_ID=GROUP), send=True, telegram=tg)
    assert "sendMessage" not in tg.calls and "re-run" in out["test_message"]["skipped"]


def test_nothing_is_sent_when_the_bot_cannot_post_or_the_token_is_rejected():
    for tg, verdict in ((FakeTelegram(status="left"), "BOT_CANNOT_SEND_IN_CHAT"),
                        (FakeTelegram(status="administrator", chat_type="channel"), "READY_TO_SEND"),
                        (FakeTelegram(chat_ok=False), "CHAT_NOT_REACHABLE"),
                        (FakeTelegram(token_ok=False), "TOKEN_REJECTED")):
        out = diag.run(env(DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN, DIAG_SECRET_TELEGRAM_CHAT_ID=GROUP), send=False,
                       telegram=tg)
        assert out["verdict"] == verdict and "sendMessage" not in tg.calls


def test_failed_send_is_reported_as_failure():
    tg = FakeTelegram(send_ok=False)
    out = diag.run(env(DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN, DIAG_SECRET_TELEGRAM_CHAT_ID=GROUP), send=True,
                   telegram=tg)
    assert out["verdict"] == "SEND_FAILED" and out["test_message"]["error_code"] == 403


def test_without_chat_id_it_lists_groups_the_bot_sees_masked():
    out = diag.run(env(DIAG_SECRET_TELEGRAM_BOT_TOKEN=TOKEN), send=True, telegram=FakeTelegram())
    assert out["verdict"] == "TOKEN_OK_NO_CHAT_ID"
    assert out["chat_discovery"]["groups_seen"] == [{"chat": "…7890", "type": "supergroup"}]
    assert "test_message" in out and "not ready" in out["test_message"]["skipped"]
