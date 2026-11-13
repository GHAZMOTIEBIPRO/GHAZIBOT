"""Telegram connection diagnosis: where the credentials are, whether they work, one proven delivery.

Run inside a GitHub Actions job. The workflow passes candidate secrets/variables as
environment variables named DIAG_<SCOPE>_<NAME> (SCOPE = SECRET or VAR). This script:

1. reports, per candidate name, only: present / length class / whitespace or quote
   damage / token shape. It never prints a value;
2. picks the canonical pair (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) or, if absent, the
   first present alternative and says which name it came from;
3. with a token: getMe (bot id and username are public), getWebhookInfo, and the
   chat: getChat (type only), getChatMember for the bot (status and send rights);
   without a chat id, getUpdates to list the chat types the bot can see;
4. with --send-test and a usable chat: sends ONE test message and reports ok and
   message_id. A re-run of the same job (run_attempt > 1) never sends again.

Output: one JSON document on stdout (also written to --output); exit code 0 when a
message was proven delivered or no send was requested, 1 when a requested test failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

TOKEN_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "TELEGRAM_API_TOKEN", "TELEGRAM_BOT_API_TOKEN",
               "BOT_TOKEN", "TG_BOT_TOKEN", "TG_TOKEN", "TELEGRAM_BOT", "TELEGRAM_KEY")
CHAT_NAMES = ("TELEGRAM_CHAT_ID", "TELEGRAM_GROUP_ID", "TELEGRAM_CHANNEL_ID", "TELEGRAM_CHATID",
              "CHAT_ID", "TG_CHAT_ID", "GROUP_ID")
CANONICAL_TOKEN, CANONICAL_CHAT = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
CHAT_RE = re.compile(r"^(-?\d{5,20}|@[A-Za-z0-9_]{5,64})$")
TIMEOUT = 20
TEST_TEXT = ("🔧 اختبار اتصال GHAZI RADAR\n"
             "رسالة تجريبية واحدة للتحقق من وصول التنبيهات إلى المجموعة. لا تحتوي إشارة تداول.\n"
             "{stamp} · run {run}")


def describe(raw: str | None, kind: str) -> dict[str, Any]:
    """Presence and damage checks. Never returns any part of the value."""
    if raw is None or raw == "":
        return {"present": False}
    stripped = raw.strip().strip('"').strip("'").strip()
    pattern = TOKEN_RE if kind == "token" else CHAT_RE
    return {
        "present": True,
        "length_class": "short" if len(raw) < 10 else "normal" if len(raw) < 80 else "long",
        "surrounding_whitespace": raw != raw.strip(),
        "surrounding_quotes": raw.strip()[:1] in "\"'" or raw.strip()[-1:] in "\"'",
        "shape_ok_as_stored": bool(pattern.match(raw)),
        "shape_ok_after_trim": bool(pattern.match(stripped)),
    }


def clean(raw: str | None) -> str:
    return (raw or "").strip().strip('"').strip("'").strip()


def mask_chat(chat_id: Any) -> str:
    text = str(chat_id)
    return text if text.startswith("@") else f"…{text[-4:]}" if len(text) > 4 else "…"


def inventory(environ: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for scope in ("SECRET", "VAR"):
        for name in TOKEN_NAMES + CHAT_NAMES:
            kind = "token" if name in TOKEN_NAMES else "chat"
            info = describe(environ.get(f"DIAG_{scope}_{name}"), kind)
            if info["present"]:
                out[f"{scope.lower()}s.{name}"] = info
    return out


def choose(environ: dict[str, str], kind: str) -> tuple[str | None, str | None]:
    """Canonical repository secret first, then any alternative name or a variable."""
    names = TOKEN_NAMES if kind == "token" else CHAT_NAMES
    for scope in ("SECRET", "VAR"):
        for name in names:
            value = clean(environ.get(f"DIAG_{scope}_{name}"))
            if value:
                return value, f"{scope.lower()}s.{name}"
    return None, None


class Telegram:
    def __init__(self, token: str, session: Any = None):
        import requests  # imported lazily so the pure helpers test without it
        self.token = token
        self.session = session or requests.Session()

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            response = self.session.post(f"https://api.telegram.org/bot{self.token}/{method}",
                                         json=params, timeout=TIMEOUT)
        except Exception as error:  # noqa: BLE001 - report the class only (a message may embed the URL)
            return {"ok": False, "error": type(error).__name__}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("ok", False)
        payload["http_status"] = response.status_code
        return payload


def probe(tg: Telegram, chat_id: str | None) -> dict[str, Any]:
    report: dict[str, Any] = {}
    me = tg.call("getMe")
    report["getMe"] = {"ok": me.get("ok"), "http_status": me.get("http_status"),
                       "error_code": me.get("error_code"), "description": me.get("description")}
    if not me.get("ok"):
        report["verdict"] = "TOKEN_REJECTED" if me.get("http_status") in (401, 404) else "TELEGRAM_UNREACHABLE"
        return report
    bot = me.get("result") or {}
    report["bot"] = {"id": bot.get("id"), "username": bot.get("username"), "is_bot": bot.get("is_bot")}
    hook = tg.call("getWebhookInfo").get("result") or {}
    report["webhook_set"] = bool(hook.get("url"))
    if not chat_id:
        updates = tg.call("getUpdates", limit=100, timeout=0)
        chats: dict[str, str] = {}
        for item in updates.get("result") or []:
            for key in ("message", "channel_post", "my_chat_member", "edited_message"):
                chat = (item.get(key) or {}).get("chat") or {}
                if chat.get("type") in ("group", "supergroup", "channel"):
                    chats[str(chat.get("id"))] = chat.get("type")
        report["chat_discovery"] = {"getUpdates_ok": updates.get("ok"), "error_code": updates.get("error_code"),
                                    "groups_seen": [{"chat": mask_chat(k), "type": v} for k, v in chats.items()]}
        report["verdict"] = "TOKEN_OK_NO_CHAT_ID"
        return report
    chat = tg.call("getChat", chat_id=chat_id)
    report["chat"] = {"ok": chat.get("ok"), "error_code": chat.get("error_code"),
                      "description": chat.get("description"), "chat": mask_chat(chat_id),
                      "type": (chat.get("result") or {}).get("type")}
    if not chat.get("ok"):
        report["verdict"] = "CHAT_NOT_REACHABLE"
        return report
    member = tg.call("getChatMember", chat_id=chat_id, user_id=bot.get("id"))
    result = member.get("result") or {}
    status = result.get("status")
    chat_type = report["chat"]["type"]
    if chat_type == "channel":
        can_send = status == "creator" or (status == "administrator" and result.get("can_post_messages") is True)
    else:
        can_send = status in ("creator", "administrator", "member") or (
            status == "restricted" and result.get("can_send_messages") is True)
    report["bot_membership"] = {"ok": member.get("ok"), "status": status, "can_send": can_send}
    report["verdict"] = "READY_TO_SEND" if can_send else "BOT_CANNOT_SEND_IN_CHAT"
    return report


def send_test(tg: Telegram, chat_id: str, *, run: str) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sent = tg.call("sendMessage", chat_id=chat_id, text=TEST_TEXT.format(stamp=stamp, run=run),
                   disable_notification=False)
    result = sent.get("result") or {}
    return {"ok": sent.get("ok"), "http_status": sent.get("http_status"), "error_code": sent.get("error_code"),
            "description": sent.get("description"), "message_id": result.get("message_id"),
            "chat": mask_chat(chat_id), "date": result.get("date")}


def run(environ: dict[str, str], *, send: bool, telegram: Telegram | None = None) -> dict[str, Any]:
    scope = environ.get("DIAG_SCOPE", "repository")
    out: dict[str, Any] = {"schema": "ghazi.telegram_diagnosis.v1", "scope": scope,
                           "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "found": inventory(environ)}
    token, token_from = choose(environ, "token")
    chat_id, chat_from = choose(environ, "chat")
    out["token_source"], out["chat_source"] = token_from, chat_from
    out["canonical_names_used"] = token_from == f"secrets.{CANONICAL_TOKEN}" and chat_from in (
        None, f"secrets.{CANONICAL_CHAT}")
    if not token:
        out["verdict"] = "NO_TOKEN_IN_THIS_SCOPE"
        return out
    tg = telegram or Telegram(token)
    out.update(probe(tg, chat_id))
    if send:
        attempt = environ.get("GITHUB_RUN_ATTEMPT", "1")
        if attempt != "1":
            out["test_message"] = {"skipped": f"re-run attempt {attempt}: never send twice"}
        elif out.get("verdict") != "READY_TO_SEND":
            out["test_message"] = {"skipped": f"not ready: {out.get('verdict')}"}
        else:
            out["test_message"] = send_test(tg, chat_id, run=environ.get("GITHUB_RUN_ID", "local"))
            out["verdict"] = "DELIVERED" if out["test_message"].get("ok") and out["test_message"].get(
                "message_id") else "SEND_FAILED"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = run(dict(os.environ), send=args.send_test)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    if args.send_test and report.get("verdict") not in ("DELIVERED", "NO_TOKEN_IN_THIS_SCOPE"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
