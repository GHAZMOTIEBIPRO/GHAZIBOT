"""Who may do what with each source's data: provider -> compute -> output policy -> sink.

Every (source, use) pair has its own decision, and anything not listed is
denied. A decision is evidence, not a key's presence:

- ALLOWED: the provider's terms or public-domain status permit the use.
- OWNER_AUTHORIZED: permitted for the owner's own internal use once the owner
  records a repository variable after reading the terms (the variable is the
  owner's attestation, not the provider's permission; keys are separate).
- UNVERIFIED: no text found that permits or forbids it; denied until verified.
- DENIED: the terms forbid it.

Uses:
  fetch            request the data automatically
  compute          analyse it internally
  store_private    keep it in runner-temporary storage (never bot-state, never
                   artifacts, never logs)
  publish_raw      show the raw values (prices, bars) on the public site
  publish_derived  show results computed from it on the public site
  telegram_private send to the owner's personal Telegram chat
  telegram_public  send to a group/channel or any shared destination
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

USES = ("fetch", "compute", "store_private", "publish_raw", "publish_derived", "telegram_private", "telegram_public")
ALLOWED, OWNER_AUTHORIZED, UNVERIFIED, DENIED = "ALLOWED", "OWNER_AUTHORIZED", "UNVERIFIED", "DENIED"

_ALPACA_TERMS = "Alpaca support: 'you cannot redistribute Alpaca API data'"
_ALPACA_DERIVED = ("no Alpaca text on derived results found (2026-10-26); vendor and exchange agreements license "
                   "derived display separately, so it is not assumed")
_PUBLIC_DOMAIN = "U.S. government publication / CC0"

# source -> use -> (status, evidence, owner variables that must be "true")
RIGHTS: dict[str, dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "alpaca_iex": {
        "fetch": (OWNER_AUTHORIZED, "account data API; owner attests the data agreement",
                  ("ALPACA_INTERNAL_DATA_USE_AUTHORIZED",)),
        "compute": (OWNER_AUTHORIZED, "internal analysis by the account holder", ("ALPACA_INTERNAL_DATA_USE_AUTHORIZED",)),
        "store_private": (OWNER_AUTHORIZED, "transient runner storage only", ("ALPACA_INTERNAL_DATA_USE_AUTHORIZED",)),
        "publish_raw": (DENIED, _ALPACA_TERMS, ()),
        "publish_derived": (UNVERIFIED, _ALPACA_DERIVED, ()),
        "telegram_private": (OWNER_AUTHORIZED, "delivery to the account holder only (not redistribution)",
                             ("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "ALPACA_PRIVATE_ALERTS_AUTHORIZED")),
        "telegram_public": (DENIED, _ALPACA_TERMS, ()),
    },
    "tradingview_widget": {
        "publish_raw": (ALLOWED, "official embed widgets displayed in the visitor's browser with branding", ()),
        "fetch": (DENIED, "widget data may not be extracted (non-display use prohibited)", ()),
        "compute": (DENIED, "non-display use prohibited", ()),
    },
}
for _official in ("treasury", "cftc", "openfda", "sec_edgar", "clinicaltrials"):
    RIGHTS[_official] = {use: (ALLOWED, _PUBLIC_DOMAIN if _official != "clinicaltrials" else
                               "NLM terms: attribution, no endorsement", ()) for use in USES}
for _blocked, _why in (("yahoo", "Yahoo terms prohibit automated access"),
                       ("nasdaq_web", "Nasdaq.com terms prohibit automated capture")):
    RIGHTS[_blocked] = {use: (DENIED, _why, ()) for use in USES}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: str
    reason: str


def decide(source: str, use: str, env: Mapping[str, str]) -> Decision:
    entry = RIGHTS.get(source, {}).get(use)
    if use not in USES or entry is None:
        return Decision(False, DENIED, f"no recorded right for {source}/{use}: denied by default")
    status, evidence, variables = entry
    if status == ALLOWED:
        return Decision(True, status, evidence)
    if status == OWNER_AUTHORIZED:
        missing = [v for v in variables if (env.get(v) or "").strip().lower() != "true"]
        if missing:
            return Decision(False, status, "owner authorization not recorded: " + ", ".join(missing))
        return Decision(True, status, evidence)
    return Decision(False, status, evidence)


def decide_all(sources: list[str], use: str, env: Mapping[str, str]) -> Decision:
    """An output is allowed only if every source feeding it allows the use."""
    for source in sources or ["<none>"]:
        decision = decide(source, use, env)
        if not decision.allowed:
            return Decision(False, decision.status, f"{source}: {decision.reason}")
    return Decision(True, ALLOWED, "all sources allow " + use)


def private_chat_ok(chat: Any) -> bool:
    """Telegram getChat result for the destination: only a one-to-one chat is private."""
    return isinstance(chat, dict) and chat.get("type") == "private"


def deliver_private(text: str, *, sources: list[str], env: Mapping[str, str],
                    get_chat: Callable[[str], Any], send: Callable[[str, str], Any]) -> str:
    """Send to the owner's own one-to-one chat only; never to a group or channel.

    The destination is the owner's chat, identified one of two ways:
    - TELEGRAM_OWNER_CHAT_ID (secret), or
    - the chat the notifiers already resolved (TELEGRAM_CHAT_ID, from the secret, the
      encrypted connection artifact or Telegram updates), when TELEGRAM_OWNER_USERNAME
      is set: that chat is used only if Telegram confirms it is the owner's account.
    Identity is checked with Telegram every time (getChat): the chat must be type
    "private" (a person, not a group or channel), and when TELEGRAM_OWNER_USERNAME is
    set its username must match. The same private chat may also receive the bot's
    general messages: both go only to the owner, so no public channel is required.
    """
    decision = decide_all(sources, "telegram_private", env)
    if not decision.allowed:
        return "DENIED_BY_POLICY"
    chat_id = (env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    username = (env.get("TELEGRAM_OWNER_USERNAME") or "").strip().lstrip("@").lower()
    if not chat_id and username:
        chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        return "OWNER_CHAT_NOT_CONFIGURED"
    try:
        chat = get_chat(chat_id)
    except Exception:  # noqa: BLE001 - destination unverified means no send
        return "DESTINATION_UNVERIFIED"
    if not private_chat_ok(chat):
        return "DESTINATION_NOT_PRIVATE"
    if username and str(chat.get("username") or "").lower() != username:
        return "OWNER_IDENTITY_MISMATCH"
    try:
        receipt = send(text, chat_id)
    except Exception:  # noqa: BLE001 - reported as status only (no URL/token in logs)
        return "SEND_FAILED"
    message_id = getattr(receipt, "message_id", None)
    return "DELIVERED" if type(message_id) is int and message_id > 0 else "UNCONFIRMED"
