"""Owner-private acceptance run: real bars -> checks -> frames -> scenarios -> save -> private send -> match.

Sample: SPY (index through its ETF), AAPL (a large-cap leader) and the first
official-catalyst candidate that is not on the known-large list. Works on the
last completed session, so it can run outside market hours; live intraday
behaviour still has to be checked during a session.

Per symbol it checks: the plan exists and is for the last closed session; the
newest bar is at least 16 minutes old; every level and scenario trigger /
invalidation is a computed number with its source bar; the feed is the same
for history and intraday. The private result is written to --private-output
(runner temp, never committed or uploaded); the message is rendered from that
saved file and its hash is compared with the hash of what was sent. The log
shows check results, feeds, frame names and hashes only: no prices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from options_radar.bar_providers import AlpacaBars
from options_radar.output_policy import decide, deliver_private
from scripts import build_daily_plan as bdp

FIXED = ("SPY", "AAPL")


def sample(catalysts: Any) -> list[str]:
    for entry in (catalysts or {}).get("watchlist") or []:
        if isinstance(entry, dict) and entry.get("universe") == "MARKET_CAP_UNVERIFIED" and entry.get("symbol"):
            return [*FIXED, entry["symbol"]]
    return list(FIXED)


def check(plan: dict[str, Any], status: dict[str, Any], facts: dict[str, Any], now: datetime) -> dict[str, bool]:
    if not plan.get("available"):
        return {"plan_available": False}
    frames = plan.get("frames") or {}
    intraday_ends = [f.get("last_bar_end") for k, f in frames.items() if k in ("4h", "1h", "15m", "5m")
                     and f.get("last_bar_end")]
    newest = max(intraday_ends) if intraday_ends else None
    levels_ok = all(isinstance(lv.get("value"), (int, float)) and lv.get("bar") for lv in plan.get("levels") or [])
    scen_ok = all(isinstance(s.get("trigger_level"), (int, float)) and isinstance(s.get("invalidation"), (int, float))
                  for s in plan.get("scenarios") or [] if s.get("kind") in ("BULLISH", "BEARISH"))
    return {"plan_available": True,
            "for_last_closed_session": plan.get("last_closed_session") == facts["last_closed_session"],
            "newest_bar_at_least_16_min_old": newest is None or
            datetime.fromisoformat(newest) <= now - timedelta(minutes=16),
            "levels_computed_with_source_bar": bool(plan.get("levels")) and levels_ok,
            "scenario_trigger_and_invalidation_computed": bool(plan.get("scenarios")) and scen_ok,
            "single_feed": len(status.get("feeds") or []) == 1}


def render(saved: dict[str, Any]) -> str:
    return bdp.private_message({"plans": saved["plans"]}, saved["facts"])


def run(now: datetime, env: Any, catalysts: Any, private_path: Path, *, session: Any = None,
        send: Any = None) -> dict[str, Any]:
    facts = bdp.calendar_facts(now)
    provider = AlpacaBars(env, now=now, **({"session": session} if session is not None else {}))
    ready = provider.status()
    report: dict[str, Any] = {"checked_at": now.isoformat(), "last_closed_session": facts["last_closed_session"],
                              "provider_status": ready}
    if ready != "READY" or not decide("alpaca_iex", "store_private", env).allowed:
        return {**report, "result": "NOT_RUN"}
    sessions = bdp._sessions(now, 60)
    plans, checks = {}, {}
    for symbol in sample(catalysts):
        plan, status = bdp.plan_from_provider(provider, symbol, facts, sessions, now)
        plans[symbol] = plan
        checks[symbol] = {"feeds": status.get("feeds"), "frames": plan.get("frames_available") or [],
                          "checks": check(plan, status, facts, now)}
    saved = {"facts": facts, "plans": plans}
    private_path.write_text(json.dumps(saved, ensure_ascii=False, default=str), encoding="utf-8")
    text = render(json.loads(private_path.read_text(encoding="utf-8")))  # rendered from what was saved
    sent_text: list[str] = []
    delivery = "NOT_ATTEMPTED"
    if send is not None:
        delivery = send(text, sent_text)
    report.update(symbols=checks, saved_sha256=hashlib.sha256(text.encode()).hexdigest()[:16],
                  sent_sha256=hashlib.sha256(sent_text[0].encode()).hexdigest()[:16] if sent_text else None,
                  delivery=delivery)
    all_ok = all(all(c["checks"].values()) for c in checks.values())
    report["message_matches_saved"] = bool(sent_text) and report["sent_sha256"] == report["saved_sha256"]
    report["result"] = "PASS" if all_ok and report["message_matches_saved"] and delivery == "DELIVERED" else "FAIL"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalysts", type=Path)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalysts = json.loads(args.catalysts.read_text(encoding="utf-8")) if args.catalysts else None
    except (OSError, ValueError):
        catalysts = None
    from scripts.telegram_transport import get_chat, send_html_message

    def send(text: str, captured: list[str]) -> str:
        def _send(body: str, chat: str) -> Any:
            captured.append(body)
            return send_html_message(body, chat_id=chat)
        return deliver_private(text, sources=["alpaca_iex"], env=os.environ, get_chat=get_chat, send=_send)

    report = run(datetime.now(timezone.utc), os.environ, catalysts, args.private_output, send=send)
    print("Acceptance:", json.dumps(report, ensure_ascii=False))  # checks, feeds, frame names, hashes: no prices
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
