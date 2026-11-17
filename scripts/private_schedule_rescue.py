"""Rescue the owner-private opening-Fibonacci schedules from late GitHub crons.

On 2026-11-16 GitHub delivered the 14:27/14:42 UTC crons of
``opening-fib-daily.yml`` at 23:27 and 23:45 UTC. The runner correctly refused
to send outside the 10:15-11:45 New York window (SKIP_OUTSIDE_LOCAL_DELIVERY_WINDOW),
so no private digest went out and the shadow scorecard had nothing to audit.

The Market Orchestrator, which keeps a reliable 5-minute cadence through its
own self-chain, calls this script every pass. It only *dispatches* the two
existing private workflows; every delivery decision stays inside their runners
(NY window, XNYS session, sent marker, rights gates). This script reads only the
date-only markers on bot-state and run metadata; it never sees prices, tokens or
chat identifiers.

Guards against duplicates:
- the daily digest is never dispatched when bot-state already records today's session;
- a run that is queued or in progress blocks a new dispatch (the workflows'
  concurrency groups also serialise runs);
- at most ``MAX_ATTEMPTS`` runs per session window, counting every event (cron,
  dispatch, push), so a delivery whose marker push failed cannot repeat forever.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FIB_WORKFLOW = "opening-fib-daily.yml"
SHADOW_WORKFLOW = "opening-fib-shadow.yml"
SENT_MARKER = "state/opening_fib/sent.json"
SHADOW_MARKER = "state/opening_fib/shadow_sent.json"
# The runner accepts 10:15-11:45 NY; stop dispatching 5 minutes early so a
# queued run still starts inside the window.
FIB_WINDOW = (time(10, 15), time(11, 40))
FIB_MISSED_AFTER = time(11, 45)
# Regular close 16:00 + the runner's 16-minute completed-bar margin, rounded up.
SHADOW_EARLIEST = time(16, 20)
SHADOW_MAX_AGE = timedelta(days=4)  # the shadow runner rejects older sessions
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class Decision:
    action: str  # dispatch | skip | missed
    reason: str


def _ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else None


def _session(raw: Any) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _runs_since(runs: list[dict[str, Any]], start: datetime) -> list[dict[str, Any]]:
    out = []
    for run in runs or []:
        created = _ts(run.get("createdAt"))
        if created is not None and created >= start:
            out.append(run)
    return out


def _active(runs: list[dict[str, Any]]) -> bool:
    return any(str(r.get("status") or "") not in ("completed", "") for r in runs or [])


def opening_fib_decision(now: datetime, sent: dict[str, Any] | None,
                         runs: list[dict[str, Any]]) -> Decision:
    if now.tzinfo is None:
        return Decision("skip", "naive clock")
    ny = now.astimezone(NY)
    today = ny.date()
    if today.weekday() >= 5:
        return Decision("skip", "weekend")
    if isinstance(sent, dict) and sent.get("sent_session") == today.isoformat():
        return Decision("skip", f"already delivered for {today}")
    clock = ny.time().replace(tzinfo=None)
    if clock < FIB_WINDOW[0]:
        return Decision("skip", "before the 10:15 New York window")
    if clock > FIB_MISSED_AFTER:
        return Decision("missed", f"no private opening Fib recorded for {today} by 11:45 New York")
    if clock > FIB_WINDOW[1]:
        return Decision("skip", "too close to the end of the window to start a new run")
    window_start = datetime.combine(today, FIB_WINDOW[0], NY).astimezone(timezone.utc)
    if _active(runs):
        return Decision("skip", "a run is queued or in progress")
    attempts = _runs_since(runs, window_start)
    if len(attempts) >= MAX_ATTEMPTS:
        return Decision("skip", f"{len(attempts)} runs already started in today's window")
    return Decision("dispatch", f"no delivery recorded for {today}; attempt {len(attempts) + 1}/{MAX_ATTEMPTS}")


def shadow_decision(now: datetime, sent: dict[str, Any] | None, shadow: dict[str, Any] | None,
                    runs: list[dict[str, Any]]) -> Decision:
    if now.tzinfo is None:
        return Decision("skip", "naive clock")
    session = _session((sent or {}).get("sent_session")) if isinstance(sent, dict) else None
    if session is None or _ts((sent or {}).get("sent_at_utc")) is None:
        return Decision("skip", "no timestamped private alert to audit")
    if isinstance(shadow, dict) and shadow.get("audited_session") == session.isoformat():
        return Decision("skip", f"shadow already delivered for {session}")
    earliest = datetime.combine(session, SHADOW_EARLIEST, NY).astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    if now < earliest:
        return Decision("skip", f"session {session} not closed yet")
    if now - earliest > SHADOW_MAX_AGE:
        return Decision("skip", f"session {session} older than the shadow audit horizon")
    if _active(runs):
        return Decision("skip", "a shadow run is queued or in progress")
    attempts = _runs_since(runs, earliest)
    if len(attempts) >= MAX_ATTEMPTS:
        return Decision("skip", f"{len(attempts)} shadow runs already started for {session}")
    return Decision("dispatch", f"audit {session}; attempt {len(attempts) + 1}/{MAX_ATTEMPTS}")


# ---------------------------------------------------------------- GitHub I/O (gh CLI)
def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def read_marker(repo: str, path: str) -> dict[str, Any] | None:
    """Date-only marker on bot-state; missing or malformed -> None."""
    try:
        raw = _gh(["api", f"repos/{repo}/contents/{path}?ref=bot-state", "--jq", ".content"])
        data = json.loads(base64.b64decode(raw.strip() or "e30=").decode("utf-8"))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def recent_runs(repo: str, workflow: str) -> list[dict[str, Any]]:
    try:
        raw = _gh(["run", "list", "--repo", repo, "--workflow", workflow, "--branch", "main", "--limit", "20",
                   "--json", "createdAt,status,conclusion,event"])
        data = json.loads(raw or "[]")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return []
    return data if isinstance(data, list) else []


def dispatch(repo: str, workflow: str) -> None:
    _gh(["workflow", "run", workflow, "--repo", repo, "--ref", "main", "-f", "dry_run=false"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print decisions without dispatching")
    args = parser.parse_args(argv)
    now = _now()
    sent = read_marker(args.repo, SENT_MARKER)
    shadow = read_marker(args.repo, SHADOW_MARKER)
    checks = (
        (FIB_WORKFLOW, opening_fib_decision(now, sent, recent_runs(args.repo, FIB_WORKFLOW))),
        (SHADOW_WORKFLOW, shadow_decision(now, sent, shadow, recent_runs(args.repo, SHADOW_WORKFLOW))),
    )
    for workflow, decision in checks:
        print(f"Private schedule rescue: {workflow} -> {decision.action} ({decision.reason})")
        if decision.action == "missed":
            print(f"::warning title=Private opening Fib missed::{decision.reason}")
        if decision.action == "dispatch" and not args.dry_run:
            dispatch(args.repo, workflow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
