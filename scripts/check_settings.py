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
- Alpaca keys: independent HTTP statuses from the data API and the paper and
  live trading account endpoints (response bodies never read or printed). Only
  called if ALPACA_INTERNAL_DATA_USE_AUTHORIZED is "true" (otherwise none is
  called). A local format check (lengths, paste faults, key-id prefix family;
  no characters) runs whenever both keys are present.
Never prints a value, a chat id, a price or a response body.
"""
from __future__ import annotations

import json
import os
import re
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
    "FINRA_API_CLIENT_ID": ("secret", "private", "finra_short_volume_private", "optional: FINRA short-sale volume"),
    "FINRA_API_CLIENT_SECRET": ("secret", "private", "finra_short_volume_private", "optional: FINRA short-sale volume"),
    "FINRA_API_AUTOMATION_APPROVED": ("variable", "private", "finra_short_volume_private, source_permissions",
                                      "optional: FINRA (owner record of a FINRA developer account; not FINRA's permission)"),
}
TG = "https://api.telegram.org/bot{token}/{method}"
# Price, options and data keys referenced by existing workflows (names only).
PROVIDER_KEYS = ("ALPHA_VANTAGE_API_KEY", "TIINGO_API_KEY", "TWELVE_DATA_API_KEY", "FINNHUB_API_KEY", "POLYGON_API_KEY",
                 "TRADIER_TOKEN", "MARKETDATA_TOKEN", "INTRINIO_API_KEY", "FRED_API_KEY", "SEC_USER_AGENT",
                 "OPENFDA_API_KEY", "BENZINGA_TOKEN", "FILINGPULSE_API_KEY")
PROVIDER_VARIABLES = ("ALPHA_VANTAGE_NON_DISPLAY_USE_AUTHORIZED", "TIINGO_NON_DISPLAY_USE_AUTHORIZED",
                      "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED", "POLYGON_NON_DISPLAY_USE_AUTHORIZED",
                      "TRADIER_INTERNAL_DATA_USE_AUTHORIZED", "FRED_AUTOMATION_APPROVED", "DATA_TERMS_CONFIRMED")


def value_class_var(raw: Any) -> str:
    raw = str(raw or "").strip().lower()
    return "UNSET" if not raw else raw if raw in ("true", "false") else "OTHER_VALUE"


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


ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/bars/latest"
ALPACA_ACCOUNT = {"paper": "https://paper-api.alpaca.markets/v2/account", "live": "https://api.alpaca.markets/v2/account"}
_KEY_ID_SHAPE = re.compile(r"^[A-Z0-9]{16,32}$")


def _value_issues(raw: str) -> list[str]:
    """Paste faults in one credential, as labels only (no character of the value is returned)."""
    value = raw.strip()
    issues = []
    if raw != value:
        issues.append("OUTER_WHITESPACE_TRIMMED")
    if any(ch.isspace() for ch in value):
        issues.append("INTERNAL_WHITESPACE")
    if any(ch in "\"'`" for ch in value):
        issues.append("QUOTE_CHARACTERS")
    if any(ord(ch) > 127 for ch in value):
        issues.append("NON_ASCII")
    if any(ch in ":=" for ch in value) or value.upper().startswith("APCA-"):
        issues.append("LABEL_PASTED_WITH_VALUE")
    return issues


def alpaca_credential_shape(key_raw: str, secret_raw: str) -> dict[str, Any]:
    """Format checks that need no network call and reveal no value.

    Reports lengths, paste faults and the key-id prefix family. The key id is
    the non-secret half of the pair (it is sent as an identifier); only the
    family label is reported, never its characters. The prefix family is the
    convention Alpaca dashboards have issued (PK paper, AK live); it is a hint
    for the owner, not proof of the account type.
    """
    key, secret = key_raw.strip(), secret_raw.strip()
    prefix = key[:2].upper()
    family = {"PK": "PAPER_STYLE_PREFIX", "AK": "LIVE_STYLE_PREFIX"}.get(prefix, "UNRECOGNIZED_PREFIX")
    pair = []
    if key and key == secret:
        pair.append("KEY_EQUALS_SECRET")
    if _KEY_ID_SHAPE.fullmatch(secret) and not _KEY_ID_SHAPE.fullmatch(key):
        pair.append("LOOKS_SWAPPED")
    elif key and secret and len(key) > len(secret):
        pair.append("KEY_LONGER_THAN_SECRET")
    return {"key_id_length": len(key), "key_id_prefix_family": family,
            "key_id_issues": _value_issues(key_raw) + ([] if _KEY_ID_SHAPE.fullmatch(key) else ["NOT_UPPERCASE_ALNUM"]),
            "secret_length": len(secret), "secret_issues": _value_issues(secret_raw), "pair_issues": pair}


def _status(session: Any, url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> str:
    """HTTP status class only; the response body is never read."""
    try:
        r = session.get(url, params=params, headers=headers, timeout=20)
    except requests.RequestException:
        return "UNREACHABLE"
    return "VALID" if r.status_code == 200 else f"REJECTED_HTTP_{r.status_code}"


def alpaca_diagnosis(data: str, paper: str, live: str) -> str:
    """Map the three independent statuses to one cause, without mixing auth with permission errors."""
    codes = (data, paper, live)
    if "REJECTED_HTTP_429" in codes:
        return "RATE_LIMITED_429_RETRY_LATER"
    if "REJECTED_HTTP_403" in codes:
        return "PERMISSION_OR_SUBSCRIPTION_403"
    if "UNREACHABLE" in codes:
        return "INCONCLUSIVE_HOST_UNREACHABLE"
    if data == "VALID":
        return ("MARKET_DATA_AND_PAPER_VALID" if paper == "VALID" else
                "LIVE_KEYS_MARKET_DATA_VALID" if live == "VALID" else "MARKET_DATA_VALID_TRADING_HOSTS_REJECTED")
    if data == "REJECTED_HTTP_401":
        if paper == "VALID":
            return "PAPER_VALID_MARKET_DATA_401"
        if live == "VALID":
            return "LIVE_VALID_MARKET_DATA_401"
        if paper == live == "REJECTED_HTTP_401":
            return "PAIR_NOT_ACCEPTED_BY_PAPER_OR_MARKET_DATA"
    return "INCONCLUSIVE_CHECK_STATUS_CODES"


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
    key_raw, secret_raw = env.get("ALPACA_API_KEY") or "", env.get("ALPACA_SECRET_KEY") or ""
    key, secret = key_raw.strip(), secret_raw.strip()
    if key and secret:
        # Local format check: no network call, so it runs with or without the attestation.
        checks["alpaca_credential_shape"] = alpaca_credential_shape(key_raw, secret_raw)
    if (env.get("ALPACA_INTERNAL_DATA_USE_AUTHORIZED") or "").strip().lower() != "true":
        checks["alpaca_keys"] = "NOT_TESTED_OWNER_ATTESTATION_NOT_RECORDED"
    elif not (key and secret):
        checks["alpaca_keys"] = "NOT_TESTED_KEYS_ABSENT"
    else:
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        checks["alpaca_keys"] = _status(session, ALPACA_DATA, headers, {"symbols": "SPY", "feed": "iex"})
        # Paper and live accounts have separate key pairs. The same pair is sent
        # to both read-only account endpoints so the owner learns which
        # environment (if any) issued it. Bodies are never read or logged.
        checks["alpaca_paper_auth"] = _status(session, ALPACA_ACCOUNT["paper"], headers)
        checks["alpaca_live_auth"] = _status(session, ALPACA_ACCOUNT["live"], headers)
        checks["alpaca_auth_diagnosis"] = alpaca_diagnosis(
            checks["alpaca_keys"], checks["alpaca_paper_auth"], checks["alpaca_live_auth"])
        # When the format says the two values sit in each other's secret, test that
        # hypothesis once (same pair, reversed, market data only). The workflows are
        # never corrected silently: the owner swaps the two GitHub secrets.
        if (checks["alpaca_keys"] == "REJECTED_HTTP_401"
                and "LOOKS_SWAPPED" in checks["alpaca_credential_shape"]["pair_issues"]):
            reversed_pair = {"APCA-API-KEY-ID": secret, "APCA-API-SECRET-KEY": key}
            probe = _status(session, ALPACA_DATA, reversed_pair, {"symbols": "SPY", "feed": "iex"})
            checks["alpaca_reversed_order_probe"] = probe
            if probe == "VALID":
                checks["alpaca_auth_diagnosis"] = "SECRETS_SWAPPED_OWNER_MUST_EXCHANGE_THE_TWO_VALUES"
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
    # Other providers the workflows already reference: presence only (the workflow passes
    # `secrets.X != ''`, never the value). A present key is not permission to use it.
    out["provider_keys"] = {name: ("PRESENT" if (env.get(f"{name}_SECRET_SET") or "").lower() == "true" else
                                   "ABSENT_OR_NOT_PASSED") for name in PROVIDER_KEYS}
    out["provider_attestations"] = {name: value_class_var(env.get(name)) for name in PROVIDER_VARIABLES}
    return out


def main() -> int:
    report = check(dict(os.environ), Path(sys.argv[1] if len(sys.argv) > 1 else "telegram_runtime/connection.json"))
    print(json.dumps(report, indent=1))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["| name | kind | received |", "|---|---|---|"]
        lines += [f"| {n} | {v['kind']} | {v['received']} |" for n, v in report["settings"].items()]
        lines += ["", "| check | result |", "|---|---|"] + [
            f"| {k} | {json.dumps(v) if isinstance(v, dict) else v} |" for k, v in report["checks"].items()]
        lines += ["", "| path | ready |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["ready"].items()]
        Path(summary).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
