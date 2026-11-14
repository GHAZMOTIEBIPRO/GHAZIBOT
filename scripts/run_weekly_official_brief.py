"""Sunday official weekly event briefing to owner's verified private Telegram.

No Alpaca calls, no market prices, no options execution, no news scraping.
Reads bot-state public sources already produced by their owning workflows.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from options_radar.opening_fib_context import collect_official_events, render_weekly_official_brief
from scripts.run_opening_fib_daily import owner_chat
from scripts.telegram_transport import send_html_message

RIYADH = ZoneInfo("Asia/Riyadh")


def _load_symbols(path: Path) -> list[str]:
    if not path.is_file():
        return []
    seen: set[str] = set()
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        sym = raw.split("#", 1)[0].strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?", sym) and sym not in seen:
            seen.add(sym)
            values.append(sym)
    return values


def _owner_recipient() -> str | None:
    return (os.environ.get("TELEGRAM_OWNER_CHAT_ID") or "").strip() or None


def run(*, now: datetime, context_dir: Path, universe: Path,
        state_path: Path, dry_run: bool = False) -> str:
    if now.tzinfo is None:
        raise ValueError("aware now required")
    now = now.astimezone(timezone.utc)
    local = now.astimezone(RIYADH)
    if not dry_run and local.weekday() != 6:  # Sunday
        return "SKIP_NOT_SUNDAY"
    day = local.date().isoformat()
    if not dry_run:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if isinstance(state, dict) and state.get("sent_date") == day:
            return "SKIP_ALREADY_SENT"

    symbols = _load_symbols(universe)
    if not symbols:
        return "WEEKLY_UNIVERSE_UNAVAILABLE"
    context = collect_official_events(context_dir, now=now, symbols=symbols)
    available = sum(x == "AVAILABLE" for x in context["sources"].values())
    if available == 0:
        return "WEEKLY_OFFICIAL_SOURCES_STALE_OR_MISSING"
    message = render_weekly_official_brief(context, now=local)
    if len(message) > 3900:
        return "WEEKLY_MESSAGE_TOO_LARGE"
    if dry_run:
        # Do not dump official full text or private owner metadata to CI logs.
        return f"WEEKLY_DRY_RUN_READY_SOURCES_{available}_EVENTS_{context['event_count']}"

    chat_id = _owner_recipient()
    if not chat_id or not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return "WEEKLY_OWNER_TELEGRAM_MISSING"
    try:
        chat = owner_chat(chat_id)
        if chat.get("type") != "private":
            return "WEEKLY_NOT_PRIVATE_CHAT"
        username = str(os.environ.get("TELEGRAM_OWNER_USERNAME") or "").strip().lower().lstrip("@")
        if username and str(chat.get("username") or "").lower() != username:
            return "WEEKLY_OWNER_IDENTITY_MISMATCH"
        receipt = send_html_message(message, chat_id=chat_id)
    except Exception:  # no secrets, URLs or provider exceptions in output
        return "WEEKLY_TELEGRAM_SEND_FAILED"
    if type(receipt.message_id) is not int or receipt.message_id <= 0:
        return "WEEKLY_UNCONFIRMED"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"sent_date": day}) + "\n", encoding="utf-8")
    return "WEEKLY_DELIVERED"


def main() -> int:
    p = argparse.ArgumentParser(description="Owner-only weekly official events")
    p.add_argument("--context-dir", type=Path, required=True)
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    status = run(now=datetime.now(timezone.utc), context_dir=args.context_dir,
                 universe=args.universe, state_path=args.state, dry_run=args.dry_run)
    print("Weekly official brief status:", status)
    if status.startswith(("SKIP_", "WEEKLY_DRY_RUN_READY")) or status == "WEEKLY_DELIVERED":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
