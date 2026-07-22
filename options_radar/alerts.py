from __future__ import annotations

import pandas as pd

from .storage import SignalStore


def format_setup(row: pd.Series) -> str:
    """Format a completed setup for the dashboard; no external delivery occurs."""

    expiry = pd.to_datetime(row["expiration"]).strftime("%Y-%m-%d")
    ratio = row.get("vol_oi")
    ratio_text = "N/A" if pd.isna(ratio) else f"{float(ratio):.2f}x"
    return (
        "NEW_SETUP\n"
        f"Ticker: {row['symbol']}\n"
        f"Contract: {expiry} | {float(row['strike']):g} {str(row['option_type']).upper()}\n"
        f"Entry limit: ${float(row['entry_price']):.2f}\n"
        f"Targets: ${float(row['target_1']):.2f} / ${float(row['target_2']):.2f}\n"
        f"Stop: ${float(row['stop_price']):.2f}\n"
        f"Score: {float(row['score']):.1f}/100 ({row['rating']})\n"
        f"Vol/OI: {ratio_text} | Activity proxy: {row['aggressor_proxy']}\n"
        f"Catalyst: {row['catalyst']}\n"
        f"Data: {row['source']} — {row['freshness_label']}\n"
        "Dashboard research setup only; verify the live quote before placing an order."
    )


def collect_new_setups(frame: pd.DataFrame, store: SignalStore) -> list[str]:
    """Return newly qualified setups once and persist deduplication state."""

    messages: list[str] = []
    if frame.empty:
        return messages
    candidates = frame.loc[frame["new_setup_candidate"] == True]  # noqa: E712
    for _, row in candidates.iterrows():
        contract = str(row["contract_symbol"])
        if store.was_alerted(contract):
            continue
        messages.append(format_setup(row))
        store.mark_alerted(
            contract,
            float(row["score"]),
            row.get("vol_oi"),
            str(row.get("source", "")),
        )
    return messages
