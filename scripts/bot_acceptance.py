"""Offline acceptance of the catalyst Telegram bot on its real published inputs.

Reads the real catalyst_watchlist.json, the real alert state and data-status.json
(from a bot-state checkout), runs the approved sender (scripts.send_catalyst_watchlist_alerts)
with a recording transport, and checks:

- content: each message is built from a real event (symbol, date, official link), never WAIT;
- destination: the broadcast destination is the one telegram_connection_bootstrap resolves (a
  private chat by the settings check); this script sends nothing, it records texts only;
- timing: the daily brief opens at 08:15 Riyadh on weekdays and is sent once per day;
- dedupe: a second run over the same inputs sends nothing new;
- recovery: when the transport fails mid-run, the unsent events stay pending and the next
  run sends exactly those, once.

It never contacts Telegram. Its output is counts and checks (no message text in the log).
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts import send_catalyst_watchlist_alerts as bot

RIYADH = ZoneInfo("Asia/Riyadh")


class Receipt:
    def __init__(self, message_id: int):
        self.message_id = message_id


class Recorder:
    def __init__(self, fail_after: int | None = None):
        self.texts: list[str] = []
        self.fail_after = fail_after

    def __call__(self, text: str) -> Receipt:
        if self.fail_after is not None and len(self.texts) >= self.fail_after:
            raise ConnectionError("simulated Telegram outage")
        self.texts.append(text)
        return Receipt(1000 + len(self.texts))


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check(report: dict[str, Any], state: dict[str, Any] | None, health: Any, now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {"now": now.isoformat(), "report_generated_at": report.get("generated_at"), "checks": {}}
    found = bot.candidates(report, now=now)
    seen = set(((state or {}).get("seen") or {}).keys())
    out["eligible"] = len(found)
    out["already_delivered"] = sum(1 for f in found if f["key"] in seen)
    # 1) content and dedupe against the real state
    rec = Recorder()
    after, summary = bot.run(report, copy.deepcopy(state), now=now, send=rec)
    out["first_run"] = {k: summary.get(k) for k in ("mode", "sent", "eligible", "pending", "failed")}
    content_ok = all(("<a href=\"https://" in t and "WAIT" not in t and "GHAZI RADAR" in t) for t in rec.texts)
    out["checks"]["content_from_real_events"] = content_ok
    rec2 = Recorder()
    _, summary2 = bot.run(report, copy.deepcopy(after), now=now + timedelta(minutes=30), send=rec2)
    out["checks"]["second_run_sends_nothing_new"] = summary2.get("sent") == 0 and not rec2.texts
    # 2) recovery: an empty state (every event new) with an outage after the first message
    fresh = {"schema": bot.SCHEMA, "seen": {}, "updated_at": now.isoformat()}
    broken = Recorder(fail_after=1)
    mid, s_fail = bot.run(report, copy.deepcopy(fresh), now=now, send=broken, maximum_new=5)
    healed = Recorder()
    _, s_heal = bot.run(report, copy.deepcopy(mid), now=now + timedelta(minutes=5), send=healed, maximum_new=5)
    out["recovery"] = {"outage_run": {k: s_fail.get(k) for k in ("sent", "pending", "failed")},
                       "next_run": {k: s_heal.get(k) for k in ("sent", "pending", "failed")}}
    # the sender sends at most 5 new events per run; the rest wait for later runs
    pending_after_outage = s_fail.get("pending") or 0
    out["checks"]["recovery_sends_only_the_unsent_once"] = (
        not found or (s_fail.get("failed") == "ConnectionError" and len(broken.texts) == 1
                      and pending_after_outage == len(found) - 1
                      and len(healed.texts) == min(pending_after_outage, 5)
                      and s_heal.get("pending") == pending_after_outage - len(healed.texts)
                      and not set(broken.texts) & set(healed.texts)))
    # 3) timing of the daily brief (Riyadh 08:15, weekdays) and once per day
    day = now.astimezone(RIYADH).replace(hour=8, minute=0, second=0, microsecond=0)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    out["checks"]["brief_not_before_0815_riyadh"] = (not bot.daily_brief_due(day.astimezone(timezone.utc))
                                                      and bot.daily_brief_due((day + timedelta(minutes=15)).astimezone(timezone.utc)))
    saturday = day + timedelta(days=(5 - day.weekday()))
    out["checks"]["no_brief_on_weekend"] = not bot.daily_brief_due((saturday + timedelta(hours=2)).astimezone(timezone.utc))
    brief_rec = Recorder()
    brief_state, b1 = bot.send_daily_brief(report, copy.deepcopy(state or {}), now=now, send=brief_rec, market_health=health)
    _, b2 = bot.send_daily_brief(report, brief_state, now=now + timedelta(hours=1), send=brief_rec, market_health=health)
    out["daily_brief"] = {"first": b1.get("mode"), "second": b2.get("mode")}
    out["checks"]["brief_at_most_once_per_day"] = b2.get("mode") in ("already_sent", "weekend", "stale_or_invalid_official_report",
                                                                      "no_verified_recent_events")
    out["passed"] = all(out["checks"].values())
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True, help="bot-state checkout")
    parser.add_argument("--now", help="ISO time to evaluate at (default: the report's generated_at + 1h)")
    args = parser.parse_args()
    data = args.state_dir / "runtime/public/data"
    report = _load(data / "catalyst_watchlist.json") or {}
    state = _load(args.state_dir / "state/catalyst/catalyst_alert_state.json")
    health = _load(data / "data-status.json")
    produced = bot._as_utc(report.get("generated_at")) or datetime.now(timezone.utc)
    now = datetime.fromisoformat(args.now) if args.now else produced + timedelta(hours=1)
    result = check(report, state, health, now)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
