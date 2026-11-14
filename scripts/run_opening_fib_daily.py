"""Owner-only daily opening Fibonacci Telegram digest.

This runner must never log, persist or publish provider price data. Only a
date-only SENT marker is written to the isolated bot-state checkout.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
import requests

from options_radar.bar_providers import AlpacaBars
from options_radar.opening_fib_scan import evaluate, render_private_digest
from options_radar.output_policy import decide, deliver_private
from scripts.telegram_transport import send_html_message

NY = ZoneInfo("America/New_York")
SYMBOLS_MAX = 300


def load_symbols(path: Path, *, maximum: int) -> list[str]:
    import re
    out: list[str] = []
    for text in path.read_text(encoding="utf-8").splitlines():
        symbol = text.partition("#")[0].strip().upper()
        if symbol and re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?", symbol) and symbol not in out:
            out.append(symbol)
    return out[:max(1, min(SYMBOLS_MAX, maximum))]


def session_open(now: datetime) -> datetime | None:
    calendar = xcals.get_calendar("XNYS")
    today = now.astimezone(NY).date()
    label = pd.Timestamp(today)
    if not calendar.is_session(label):
        return None
    return pd.Timestamp(calendar.schedule.loc[str(today), "open"]).to_pydatetime().astimezone(timezone.utc)


def owner_chat(chat_id: str) -> dict[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("missing Telegram bot")
    res = requests.get(
        f"https://api.telegram.org/bot{token}/getChat",
        params={"chat_id": chat_id}, timeout=12,
    )
    res.raise_for_status()
    body = res.json()
    if not body.get("ok") or not isinstance(body.get("result"), dict):
        raise RuntimeError("Telegram getChat not verified")
    chat = body["result"]
    return {"type": str(chat.get("type") or ""), "username": str(chat.get("username") or "")}


def preflight(now: datetime) -> str:
    """No-send readiness diagnostics: independently check SIP, private chat, rights.

    This checks a historical consolidated SPY opening and the destination's
    private Telegram identity without sending any message. Logs include only
    bounded status codes; no quotes, credentials, usernames or chat IDs.
    """
    env = dict(os.environ)
    provider = AlpacaBars(env, now=now)
    if provider.status() != "READY":
        print("Preflight Alpaca source: NOT_READY")
        return "PREFLIGHT_ALPACA_KEY_OR_RIGHTS_MISSING"
    for use in ("fetch", "compute"):
        if not decide(provider.rights_source, use, env).allowed:
            print("Preflight Alpaca data rights: DENIED")
            return "PREFLIGHT_RIGHTS_DENIED_" + use.upper()
    print("Preflight Alpaca data computation: ALLOWED")

    # Read-only diagnostics for the chat and historical consolidated SIP are
    # independent of permission to SEND licensed prices. A missing attestation
    # must never prevent us identifying another installation fault.
    delivery_allowed = decide(provider.rights_source, "telegram_private", env).allowed
    print("Preflight private price delivery:", "AUTHORIZED" if delivery_allowed else "NOT_AUTHORIZED")

    chat_problem = None
    chat_id = (env.get("TELEGRAM_OWNER_CHAT_ID") or "").strip()
    username = (env.get("TELEGRAM_OWNER_USERNAME") or "").strip().lstrip("@").lower()
    if not chat_id and username:
        chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        chat_problem = "PREFLIGHT_OWNER_CHAT_NOT_SET"
    else:
        try:
            chat = owner_chat(chat_id)
        except (requests.RequestException, RuntimeError, ValueError):
            chat_problem = "PREFLIGHT_TELEGRAM_UNREACHABLE"
        else:
            if chat.get("type") != "private":
                chat_problem = "PREFLIGHT_CHAT_NOT_PRIVATE"
            elif username and str(chat.get("username") or "").lower() != username:
                chat_problem = "PREFLIGHT_OWNER_IDENTITY_MISMATCH"
    print("Preflight private Telegram destination:",
          "VERIFIED" if chat_problem is None else chat_problem)

    sip_problem = None
    calendar = xcals.get_calendar("XNYS")
    end_date = now.astimezone(NY).date()
    schedule = calendar.schedule.loc[
        str(end_date - timedelta(days=15)):str(end_date)
    ]
    if schedule.empty:
        sip_problem = "PREFLIGHT_NO_RECENT_MARKET_SESSION"
    else:
        recent_open = pd.Timestamp(schedule.iloc[-1]["open"]).to_pydatetime()
        result = provider.bars(
            "SPY", "5m", recent_open, recent_open + timedelta(minutes=15)
        )
        if result.get("status") != "OK" or result.get("feed") != "sip":
            sip_problem = "PREFLIGHT_HISTORICAL_SIP_UNAVAILABLE"
        else:
            stamps = {
                row.get("t").astimezone(timezone.utc)
                for row in result.get("bars", [])
                if isinstance(row, dict)
                and isinstance(row.get("t"), datetime)
                and row["t"].tzinfo is not None
            }
            if any(recent_open + timedelta(minutes=5 * i) not in stamps
                   for i in range(3)):
                sip_problem = "PREFLIGHT_OPENING_BARS_INCOMPLETE"
    print("Preflight historical consolidated SIP:",
          "VERIFIED" if sip_problem is None else sip_problem)

    # Denied-by-default: a successful read/identity test is NEVER permission
    # to send a licensed price to Telegram.
    if not delivery_allowed:
        return "PREFLIGHT_RIGHTS_DENIED_TELEGRAM_PRIVATE"
    if chat_problem:
        return chat_problem
    if sip_problem:
        return sip_problem
    return "PREFLIGHT_READY"


def run(*, now: datetime, universe: Path, state_path: Path, dry_run: bool,
        max_symbols: int) -> str:
    now = now.astimezone(timezone.utc)
    ny_now = now.astimezone(NY)
    opening = session_open(now)
    if opening is None:
        return "SKIP_NON_SESSION"
    # Two UTC crons cover both DST and standard time; only the matching local
    # 10:xx New York window is active. GitHub schedules can arrive late.
    if not time(10, 15) <= ny_now.time().replace(tzinfo=None) <= time(11, 45):
        return "SKIP_OUTSIDE_LOCAL_DELIVERY_WINDOW"
    session_date = ny_now.date().isoformat()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    if state.get("sent_session") == session_date and not dry_run:
        return "ALREADY_DELIVERED"

    env = dict(os.environ)
    provider = AlpacaBars(env, now=now)
    if provider.status() != "READY":
        return "DATA_PROVIDER_NOT_READY"
    if not decide(provider.rights_source, "compute", env).allowed:
        return "DATA_COMPUTE_NOT_AUTHORIZED"
    if not decide(provider.rights_source, "telegram_private", env).allowed:
        return "PRIVATE_DELIVERY_NOT_AUTHORIZED"

    symbols = load_symbols(universe, maximum=max_symbols)
    if not symbols:
        return "EMPTY_UNIVERSE"
    # Delayed SIP when entitled; IEX fallback labels coverage honestly.
    # A tight request from session open prevents pulling unneeded historical bars.
    multi = provider.multi_bars(symbols, "5m", opening, now, batch=70)
    if multi.get("status") != "OK":
        return "DATA_BATCHES_FAILED"
    min_opening_notional = float(os.getenv("OPENING_FIB_MIN_OPENING_NOTIONAL", "1000000"))
    if not 0 <= min_opening_notional <= 1_000_000_000:
        return "INVALID_LIQUIDITY_THRESHOLD"
    results = [
        evaluate(
            symbol,
            multi.get("bars", {}).get(symbol, []),
            session_open=opening,
            now=now,
            feed=str(multi.get("feed", {}).get(symbol) or ""),
            min_opening_notional=min_opening_notional,
        )
        for symbol in symbols
    ]
    valid = sum(item["state"] != "NO_DATA" for item in results)
    sip_valid = sum(item.get("feed") == "sip" for item in results)
    if valid and sip_valid == 0:
        return "NO_CONSOLIDATED_SIP_COVERAGE"
    if valid == 0 or multi.get("failed_batches"):
        # An incomplete scan must not be announced as an "all stocks" report.
        return "NO_COMPLETE_SCAN"
    message = render_private_digest(results, session_date=session_date)

    if dry_run:
        # Never emit licensed price levels into public CI logs.
        return f"DRY_RUN_CHECKED_{len(results)}_VALID_{valid}"
    status = deliver_private(
        message, sources=[provider.rights_source], env=env,
        get_chat=owner_chat,
        send=lambda text, chat_id: send_html_message(text, chat_id=chat_id),
    )
    if status == "DELIVERED":
        state_path.parent.mkdir(parents=True, exist_ok=True)
        # Only a date, not any licensed quote, symbol-level result or chat ID.
        state_path.write_text(json.dumps({"sent_session": session_date},
                                         ensure_ascii=False) + "\n", encoding="utf-8")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Owner-private 15m opening Fibonacci scan")
    parser.add_argument("--universe", type=Path, default=Path("data/universe.txt"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--max-symbols", type=int,
                        default=int(os.environ.get("OPENING_FIB_MAX_SYMBOLS", "150")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight", action="store_true", help="Verify SIP and private Telegram without sending")
    args = parser.parse_args()
    status = (preflight(datetime.now(timezone.utc)) if args.preflight else
              run(now=datetime.now(timezone.utc), universe=args.universe,
                  state_path=args.state, max_symbols=args.max_symbols, dry_run=args.dry_run))
    print("Opening Fibonacci scan status:", status)
    # Weekend, wrong local time, or duplicate are legitimate non-events.
    if status.startswith(("SKIP_", "ALREADY_", "DRY_RUN_")) or status == "PREFLIGHT_READY":
        return 0
    return 0 if status == "DELIVERED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
