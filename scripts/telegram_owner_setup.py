"""Owner Telegram onboarding and harmless transport test.

No provider data is accessed or sent here. Owner registration is deliberately
NOT automatic: the user reads their own chat ID in a private Telegram reply
and explicitly stores it as a GitHub Actions secret.
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from typing import Any

import requests

from scripts.telegram_transport import send_html_message

MAX_COMMAND_AGE_SEC = 45 * 60


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _get(token: str, method: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(_api(token, method), params=params, timeout=15)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise RuntimeError("Telegram API response invalid")
    return body


def owner_id_help(*, now: datetime | None = None) -> str:
    """Reply ONLY to a recent, explicit /ghazi_id command in a one-to-one chat.

    Nothing is displayed in GitHub logs except a fixed status string.
    This helps obtain a chat ID without showing a bot token in a URL or using
    a third-party ID bot. Does not auto-authorize the chat or persist its ID.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("aware time required")
    token = _token()
    if not token:
        return "OWNER_ID_BOT_TOKEN_MISSING"
    try:
        webhook = _get(token, "getWebhookInfo")
        if str((webhook.get("result") or {}).get("url") or "").strip():
            return "OWNER_ID_WEBHOOK_ACTIVE"
        # getUpdates and webhooks are mutually exclusive. Do not disable a
        # webhook or confirm/consume updates (no offset) during this probe.
        updates = _get(token, "getUpdates", params={"limit": 100, "timeout": 0})
    except (requests.RequestException, ValueError, RuntimeError):
        return "OWNER_ID_UPDATES_UNAVAILABLE"

    target_username = (os.getenv("TELEGRAM_OWNER_USERNAME") or "").strip().lower().lstrip("@")
    match: tuple[str, str] | None = None
    for update in reversed(updates.get("result") or []):
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            continue
        command = str(message.get("text") or "").strip().split(maxsplit=1)[0].lower()
        if command != "/ghazi_id" and not command.startswith("/ghazi_id@"):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = chat.get("id")
        sender_id = sender.get("id")
        if (chat.get("type") != "private" or type(chat_id) is not int
                or sender_id != chat_id):
            continue
        try:
            age = now.timestamp() - int(message.get("date"))
        except (TypeError, ValueError):
            continue
        if age < -60 or age > MAX_COMMAND_AGE_SEC:
            continue
        if target_username and str(sender.get("username") or "").lower() != target_username:
            continue
        match = str(chat_id), str(sender.get("first_name") or "")
        break

    if match is None:
        return "OWNER_ID_COMMAND_NOT_FOUND"
    chat_id, first_name = match
    body = (
        "<b>غازي رادار | رقم محادثتك الخاصة</b>\n"
        f"مرحبًا {html.escape(first_name[:60])}\n"
        f"<code>{html.escape(chat_id)}</code>\n"
        "انسخ الرقم إلى GitHub → Settings → Secrets and variables → "
        "Actions → New repository secret.\n"
        "<b>Name:</b> <code>TELEGRAM_OWNER_CHAT_ID</code>\n"
        "<b>Secret:</b> الرقم أعلاه.\n"
        "لا ترسل مفتاح البوت إلى أي شخص."
    )
    try:
        sent = send_html_message(body, chat_id=chat_id)
    except (requests.RequestException, ValueError, RuntimeError):
        return "OWNER_ID_REPLY_FAILED"
    return "OWNER_ID_REPLIED_PRIVATELY" if type(sent.message_id) is int and sent.message_id > 0 else "OWNER_ID_REPLY_UNCONFIRMED"


def telegram_connectivity_test() -> str:
    """Owner-requested test message, no Alpaca/private price fields."""
    token = _token()
    if not token:
        return "TELEGRAM_TEST_BOT_TOKEN_MISSING"
    chat_id = (os.getenv("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    owner_username = (os.getenv("TELEGRAM_OWNER_USERNAME") or "").strip().lstrip("@").lower()
    if not chat_id and owner_username:
        chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        return "TELEGRAM_TEST_OWNER_CHAT_NOT_SET"
    try:
        result = _get(token, "getChat", params={"chat_id": chat_id}).get("result")
        if not isinstance(result, dict) or result.get("type") != "private":
            return "TELEGRAM_TEST_CHAT_NOT_PRIVATE"
        if owner_username and str(result.get("username") or "").lower() != owner_username:
            return "TELEGRAM_TEST_OWNER_IDENTITY_MISMATCH"
        message = (
            "<b>غازي رادار | اختبار اتصال ناجح</b>\n"
            "هذه رسالة تجريبية فقط. لا تحتوي بيانات Alpaca، "
            "ولا توصية CALL/PUT، ولا تعني أن الجدولة اليومية اكتملت."
        )
        receipt = send_html_message(message, chat_id=chat_id)
    except (requests.RequestException, RuntimeError, ValueError):
        return "TELEGRAM_TEST_SEND_FAILED"
    return "TELEGRAM_TEST_DELIVERED" if type(receipt.message_id) is int and receipt.message_id > 0 else "TELEGRAM_TEST_UNCONFIRMED"
