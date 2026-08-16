from __future__ import annotations

# Backward-compatible import path for market workflows that already load the
# options_radar package. The transport itself intentionally lives under scripts/
# so lightweight Telegram-only jobs do not import pandas or the market engine.
from scripts.telegram_transport import (
    TELEGRAM_TEXT_MAX_CHARS,
    TELEGRAM_TIMEOUT_SECONDS,
    TelegramEditResult,
    TelegramSendResult,
    edit_html_message,
    send_html_message,
    verify_bot,
)

__all__ = [
    "TELEGRAM_TEXT_MAX_CHARS",
    "TELEGRAM_TIMEOUT_SECONDS",
    "TelegramEditResult",
    "TelegramSendResult",
    "edit_html_message",
    "send_html_message",
    "verify_bot",
]
