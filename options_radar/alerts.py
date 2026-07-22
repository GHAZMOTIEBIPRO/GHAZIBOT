from __future__ import annotations

import logging

import pandas as pd
import requests

from .settings import Settings
from .storage import SignalStore

LOGGER = logging.getLogger(__name__)


def format_alert(row: pd.Series) -> str:
    expiry = pd.to_datetime(row["expiration"]).strftime("%Y-%m-%d")
    ratio = row.get("vol_oi")
    ratio_text = "N/A" if pd.isna(ratio) else f"{float(ratio):.2f}x"
    return (
        "🚨 NEW_INDEPENDENT_SETUP\n"
        f"Ticker: {row['symbol']}\n"
        f"Contract: {expiry} | {float(row['strike']):g} {str(row['option_type']).upper()}\n"
        f"Entry limit: ${float(row['entry_price']):.2f}\n"
        f"Targets: ${float(row['target_1']):.2f} / ${float(row['target_2']):.2f}\n"
        f"Stop: ${float(row['stop_price']):.2f}\n"
        f"Score: {float(row['score']):.1f}/100 ({row['rating']})\n"
        f"Vol/OI: {ratio_text} | Side proxy: {row['aggressor_proxy']}\n"
        f"Catalyst: {row['catalyst']}\n"
        f"Data: {row['source']} — {row['freshness_label']}\n"
        "Research signal only; verify the live quote before placing an order."
    )


def _send_telegram(settings: Settings, message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=15,
    )
    response.raise_for_status()


def _send_discord(settings: Settings, message: str) -> None:
    if not settings.discord_webhook_url:
        return
    response = requests.post(settings.discord_webhook_url, json={"content": message[:1900]}, timeout=15)
    response.raise_for_status()


def dispatch_new_alerts(frame: pd.DataFrame, settings: Settings, store: SignalStore,
                        send: bool = False) -> list[str]:
    messages: list[str] = []
    if frame.empty:
        return messages
    candidates = frame.loc[frame["new_setup_candidate"] == True]
    for _, row in candidates.iterrows():
        contract = str(row["contract_symbol"])
        if store.was_alerted(contract):
            continue
        message = format_alert(row)
        messages.append(message)
        if send:
            try:
                _send_telegram(settings, message)
                _send_discord(settings, message)
            except requests.RequestException as exc:
                LOGGER.error("Alert delivery failed for %s: %s", contract, exc)
                continue
        store.mark_alerted(contract, float(row["score"]), row.get("vol_oi"), str(row.get("source", "")))
    return messages
