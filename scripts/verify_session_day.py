"""Acceptance check of one session day from bot-state records (statuses and times only; no market data).

Usage: python -m scripts.verify_session_day --state ../state --date 2026-11-30

Reads what the runners recorded on bot-state and judges each stage against its window, in New York and
Riyadh time. A Telegram acceptance (DELIVERED) is the Bot API accepting the message, not a read receipt;
UNCONFIRMED means the request may have arrived (never resent automatically; /confirm after a manual look).
Windows (New York): EARLY delivered by 09:00, FINAL by 09:30, OPENING between open+31 and open+60 minutes,
LASTHOUR before the close, POSTCLOSE by close+120 minutes. Early closes come from the XNYS calendar.
Exit code 0 = every planned stage PASS, 1 = something to look at (printed), 2 = no records for the day.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

NY = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _t(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _both(t: datetime | None) -> str:
    return f"{t.astimezone(NY):%H:%M} NY / {t.astimezone(RIYADH):%H:%M} RUH" if t else "—"


def windows(day: str) -> dict[str, tuple[datetime, datetime]]:
    sched = xcals.get_calendar("XNYS").schedule.loc[day:day]
    if sched.empty:
        return {}
    open_at = pd.Timestamp(sched.iloc[0]["open"]).to_pydatetime()
    close_at = pd.Timestamp(sched.iloc[0]["close"]).to_pydatetime()
    d = open_at.astimezone(NY)
    at = lambda h, m: d.replace(hour=h, minute=m, second=0, microsecond=0)
    return {"EARLY": (at(8, 30), at(9, 0)), "FINAL": (at(9, 0), at(9, 30)),
            "OPENING": (open_at + timedelta(minutes=31), open_at + timedelta(minutes=60)),
            "LASTHOUR": (close_at - timedelta(minutes=60), close_at),
            "POSTCLOSE": (close_at + timedelta(minutes=20), close_at + timedelta(minutes=120))}


def judge(day: str, day_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for slot, (start, end) in windows(day).items():
        name = f"report_{slot}.json" if slot in ("EARLY", "FINAL") else f"session_{slot}.json"
        m = _load(day_dir / name)
        if not m:
            rows.append({"stage": slot, "verdict": "MISSING", "window": f"{_both(start)} – {_both(end)}"})
            continue
        items = m.get("items") or {}
        times = sorted(t for t in (_t(i.get("at")) for i in items.values() if i.get("status") == "DELIVERED") if t)
        first = times[0] if times else _t(m.get("sent_at"))
        last = times[-1] if times else first
        unconfirmed = sum(1 for i in items.values() if i.get("status") == "UNCONFIRMED")
        status = m.get("status")
        ok = status == "DELIVERED" and last is not None and start - timedelta(minutes=1) <= first and last <= end
        verdict = "PASS" if ok else ("LATE" if status == "DELIVERED" else str(status or "UNKNOWN"))
        rows.append({"stage": slot, "verdict": verdict, "status": status, "attempt": m.get("attempt"),
                     "messages": m.get("messages"), "accepted": m.get("accepted"), "unconfirmed": unconfirmed,
                     "first_accepted": _both(first), "last_accepted": _both(last),
                     "window": f"{_both(start)} – {_both(end)}"})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("../state"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    day_dir = args.state / "state" / "daily_plan" / args.date
    if not windows(args.date):
        print(json.dumps({"date": args.date, "verdict": "NOT_A_SESSION_DAY"}))
        return 0
    if not day_dir.exists():
        print(json.dumps({"date": args.date, "verdict": "NO_RECORDS"}))
        return 2
    rows = judge(args.date, day_dir)
    events = len((_load(day_dir / "session_events.json")).get("sent") or [])
    small = _load(args.state / "state" / "smallcaps" / f"{args.date}.tags.json")
    hunter = _load(args.state / "state" / "options_hunter" / "last_top.json")
    extra = {"intraday_events_sent": events,
             "smallcap_alerts_sent": small.get("alerts_sent") if small.get("day") == args.date else 0,
             "options_alert_tags": len(hunter.get("alerted") or []) if hunter.get("day") == args.date else 0}
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(json.dumps({"date": args.date, **extra}))
    return 0 if all(r["verdict"] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
