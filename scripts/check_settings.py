"""Runner check of the repository settings the private and public paths read.

Prints, per canonical name: whether the job received it (secret: non-empty;
variable: its value class), and where a check is possible without exposing a
value, whether it works:
- TELEGRAM_BOT_TOKEN: Telegram getMe answers ok.
- the broadcast destination (resolved by .github/actions/resolve-telegram-broadcast):
  how it was found and Telegram's chat type for it.
- the owner chat (TELEGRAM_OWNER_CHAT_ID, or the resolved broadcast chat when
  TELEGRAM_OWNER_USERNAME is set): Telegram's chat type (must be "private") and,
  when a username is set, whether Telegram's username for that chat matches.
- Alpaca keys: an HTTP status from the market-data API, only when the owner's
  ALPACA_INTERNAL_DATA_USE_AUTHORIZED is "true" (otherwise not called).
Never prints a value, a chat id, a price or a response body.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

# name -> (kind, use, consumers, required_for)
CANON: dict[str, tuple[str, str, str, str]] = {
    "TELEGRAM_BOT_TOKEN": ("secret", "public+private", "all Telegram senders", "any Telegram delivery"),
    "TELEGRAM_CHAT_ID": ("secret", "public", "public notifiers via telegram_connection_bootstrap",
                         "optional: else the encrypted artifact or Telegram updates"),
    "TELEGRAM_OWNER_CHAT_ID": ("secret", "private", "output_policy.deliver_private",
                               "private alerts: either this, or TELEGRAM_OWNER_USERNAME"),
    "TELEGRAM_OWNER_USERNAME": ("variable", "private", "output_policy.deliver_private",
                                "private alerts to the already-resolved one-to-one chat, verified by username"),
    "ALPACA_API_KEY": ("secret", "private", "bar_providers.AlpacaBars, alpaca_vcp_private, stream/options",
                       "any Alpaca data"),
    "ALPACA_SECRET_KEY": ("secret", "private", "same as ALPACA_API_KEY", "any Alpaca data"),
    "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": ("variable", "private", "output_policy (fetch/compute/store_private)",
                                           "any Alpaca data (owner attestation, not provider permission)"),
    "ALPACA_PRIVATE_ALERTS_AUTHORIZED": ("variable", "private", "output_policy (telegram_private)",
                                        "private alerts"),
    "ALPACA_BARS_FEED": ("variable", "private", "bar_providers.AlpacaBars", "optional: sip (default) or iex"),
    "ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": ("variable", "private", "alpaca_vcp_private",
                                                 "optional: SIP history in the VCP research"),
}
TG = "https://api.telegram.org/bot{token}/{method}"


def value_class(name: str, env: dict[str, str]) -> str:
    raw = (env.get(name) or "").strip()
    # The resolve step exports a found broadcast chat as TELEGRAM_CHAT_ID; whether
    # the secret itself exists is recorded before that step.
    flag = (env.get(f"{name}_SECRET_SET") or "").strip().lower()
    if CANON[name][0] == "secret" and flag in ("true", "false"):
        return "PRESENT" if flag == "true" else "ABSENT_OR_NOT_PASSED"
    if CANON[name][0] == "secret":
        return "PRESENT" if raw else "ABSENT_OR_NOT_PASSED"
    if not raw:
        return "UNSET"
    if name == "TELEGRAM_OWNER_USERNAME":
        return "SET"
    return raw.lower() if raw.lower() in ("true", "false", "sip", "iex") else "OTHER_VALUE"


def chat_info(token: str, chat_id: str, session: Any = requests) -> dict[str, Any] | str:
    try:
        r = session.get(TG.format(token=token, method="getChat"), params={"chat_id": chat_id}, timeout=15)
        body = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        return "UNREACHABLE"
    result = body.get("result") if isinstance(body, dict) and body.get("ok") is True else None
    return result if isinstance(result, dict) else f"NOT_FOUND_HTTP_{r.status_code}"


def chat_type(token: str, chat_id: str, session: Any = requests) -> str:
    info = chat_info(token, chat_id, session)
    return str(info.get("type")) if isinstance(info, dict) else info


def check(env: dict[str, str], connection: Path, session: Any = requests) -> dict[str, Any]:
    out: dict[str, Any] = {"settings": {n: {"received": value_class(n, env), "kind": k, "use": u,
                                             "consumers": c, "required_for": q}
                                        for n, (k, u, c, q) in CANON.items()}}
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    checks: dict[str, Any] = {}
    if token:
        try:
            r = session.get(TG.format(token=token, method="getMe"), timeout=15)
            checks["bot_token"] = "VALID" if r.status_code == 200 and r.json().get("ok") is True else f"INVALID_HTTP_{r.status_code}"
        except (requests.RequestException, ValueError):
            checks["bot_token"] = "UNREACHABLE"
    broadcast = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    try:
        source = json.loads(connection.read_text(encoding="utf-8")).get("source")
    except (OSError, ValueError, AttributeError):
        source = None
    checks["broadcast_resolved"] = bool(broadcast)
    checks["broadcast_source"] = source or ("github_secret" if broadcast else "NONE")
    checks["broadcast_chat_type"] = chat_type(token, broadcast, session) if token and broadcast else "NOT_CHECKED"
    owner = (env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    username = (env.get("TELEGRAM_OWNER_USERNAME") or "").strip().lstrip("@").lower()
    checks["owner_source"] = ("TELEGRAM_OWNER_CHAT_ID" if owner else
                              "BROADCAST_CHAT_VERIFIED_BY_USERNAME" if username and broadcast else "NONE")
    owner = owner or (broadcast if username else "")
    info = chat_info(token, owner, session) if token and owner else "NOT_CHECKED"
    checks["owner_chat_type"] = str(info.get("type")) if isinstance(info, dict) else info
    # the username itself is never printed, only whether it matches
    checks["owner_username_matches"] = ((str(info.get("username") or "").lower() == username)
                                        if username and isinstance(info, dict) else "NOT_CHECKED")
    checks["owner_is_broadcast_chat"] = bool(owner and broadcast and owner == broadcast)
    key, secret = (env.get("ALPACA_API_KEY") or "").strip(), (env.get("ALPACA_SECRET_KEY") or "").strip()
    if (env.get("ALPACA_INTERNAL_DATA_USE_AUTHORIZED") or "").strip().lower() != "true":
        checks["alpaca_keys"] = "NOT_TESTED_OWNER_ATTESTATION_NOT_RECORDED"
    elif not (key and secret):
        checks["alpaca_keys"] = "NOT_TESTED_KEYS_ABSENT"
    else:
        try:
            r = session.get("https://data.alpaca.markets/v2/stocks/bars/latest", params={"symbols": "SPY", "feed": "iex"},
                            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}, timeout=20)
            checks["alpaca_keys"] = "VALID" if r.status_code == 200 else f"REJECTED_HTTP_{r.status_code}"
        except requests.RequestException:
            checks["alpaca_keys"] = "UNREACHABLE"
    out["checks"] = checks
    ready = {
        "public_telegram": checks.get("bot_token") == "VALID" and checks["broadcast_resolved"],
        "private_price_analysis": checks["alpaca_keys"] == "VALID",
        "private_alerts": (checks["alpaca_keys"] == "VALID"
                           and out["settings"]["ALPACA_PRIVATE_ALERTS_AUTHORIZED"]["received"] == "true"
                           and checks["owner_chat_type"] == "private"
                           and checks["owner_username_matches"] in (True, "NOT_CHECKED")),
    }
    out["ready"] = ready
    return out


def main() -> int:
    report = check(dict(os.environ), Path(sys.argv[1] if len(sys.argv) > 1 else "telegram_runtime/connection.json"))
    print(json.dumps(report, indent=1))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["| name | kind | received |", "|---|---|---|"]
        lines += [f"| {n} | {v['kind']} | {v['received']} |" for n, v in report["settings"].items()]
        lines += ["", "| check | result |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["checks"].items()]
        lines += ["", "| path | ready |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["ready"].items()]
        Path(summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
