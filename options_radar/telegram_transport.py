from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests

TELEGRAM_TIMEOUT_SECONDS = 20
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: int | None
    attempts: int


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    parameters = payload.get("parameters") if isinstance(payload, dict) else {}
    if isinstance(parameters, dict):
        value = parameters.get("retry_after")
        try:
            if value is not None:
                return min(30.0, max(0.5, float(value)))
        except (TypeError, ValueError):
            pass
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(30.0, max(0.5, float(header)))
        except ValueError:
            pass
    return min(8.0, 0.8 * (2**attempt))


def send_html_message(
    text: str,
    *,
    token: str | None = None,
    chat_id: str | None = None,
    max_attempts: int = 3,
    timeout: int = TELEGRAM_TIMEOUT_SECONDS,
) -> TelegramSendResult:
    """Send one Telegram message with bounded retries on explicit server/rate failures.

    Connection/read timeouts are intentionally not blindly retried after the POST because
    Telegram may already have accepted the message, which could create duplicate alerts.
    Dedupe is therefore kept in the higher-level alert state as the primary guard.
    """

    bot_token = str(token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    destination = str(chat_id or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not bot_token or not destination:
        raise RuntimeError("Telegram destination is not ready")
    if not text.strip():
        raise ValueError("Telegram message is empty")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    response: requests.Response | None = None
    for attempt in range(max_attempts):
        try:
            response = requests.post(
                _telegram_url(bot_token, "sendMessage"),
                data={
                    "chat_id": destination,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                timeout=timeout,
            )
        except (requests.ConnectionError, requests.Timeout):
            # POST outcome is ambiguous after transport failure; avoid duplicate resend.
            raise

        if response.status_code in _RETRYABLE_STATUS and attempt + 1 < max_attempts:
            time.sleep(_retry_after_seconds(response, attempt))
            continue

        response.raise_for_status()
        body: Any = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError("Telegram rejected message")
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        message_id = result.get("message_id")
        try:
            message_id = int(message_id) if message_id is not None else None
        except (TypeError, ValueError):
            message_id = None
        return TelegramSendResult(message_id=message_id, attempts=attempt + 1)

    if response is None:
        raise RuntimeError("Telegram request did not execute")
    response.raise_for_status()
    raise RuntimeError("Telegram send exhausted retries")


def verify_bot(token: str | None = None, timeout: int = 12) -> dict[str, Any]:
    bot_token = str(token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        return {"ok": False, "reason": "missing_token"}
    try:
        response = requests.get(_telegram_url(bot_token, "getMe"), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}
    result = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else {}
    return {
        "ok": bool(payload.get("ok")) if isinstance(payload, dict) else False,
        "bot_id": result.get("id"),
        "username": result.get("username"),
    }
