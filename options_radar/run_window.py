"""Stateless dedupe: "what is new since the last successful run" from the run history, not stored state.

Owner and audit (RELEASE GATE): dedupe state derived from restricted data is not kept anywhere public,
and the standing gate keeps Alpaca-key workflows off actions/cache. So each run asks GitHub when this
workflow last ran successfully today (operational metadata, already public) and recomputes, from the
source data at run time, what changed after that moment. Nothing about any alert is stored.

Failure semantics: a run that delivered nothing because Telegram refused exits non-zero, so the next run
still measures from the last successful run and resends it while valid; a run that delivered something
exits 0 (a later message's failure is then lost, never duplicated). UNCONFIRMED counts as delivered.
If the history cannot be read, callers send no event alerts (fail safe).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests

API = "https://api.github.com"


def previous_success(env: dict[str, str], workflow: str, now: datetime, *, day_start: datetime,
                     http: Any = requests) -> tuple[str, datetime | None]:
    """("OK", start) of the latest successful run today other than this one; ("NONE_TODAY", None); ("UNKNOWN", None)."""
    repo, token = env.get("GITHUB_REPOSITORY"), env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not repo or not token:
        return "UNKNOWN", None
    try:
        r = http.get(f"{API}/repos/{repo}/actions/workflows/{workflow}/runs",
                     params={"status": "success", "per_page": 20, "created": f">={day_start.date().isoformat()}"},
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=15)
        if r.status_code != 200:
            return "UNKNOWN", None
        runs = r.json().get("workflow_runs") or []
    except (requests.RequestException, ValueError):
        return "UNKNOWN", None
    this = str(env.get("GITHUB_RUN_ID") or "")
    starts = []
    for run in runs:
        if str(run.get("id")) == this or run.get("event") == "push":
            continue
        t = datetime.fromisoformat(str(run.get("run_started_at") or run.get("created_at")).replace("Z", "+00:00"))
        if day_start <= t < now:
            starts.append(t)
    return ("OK", max(starts)) if starts else ("NONE_TODAY", None)


def data_horizon(run_start: datetime, delay_minutes: int = 16, bucket_minutes: int = 5) -> datetime:
    """The latest completed bucket end a run starting at run_start could use (SIP history >= delay old)."""
    t = run_start - timedelta(minutes=delay_minutes)
    return t.replace(minute=t.minute - t.minute % bucket_minutes, second=0, microsecond=0)


def exit_code(statuses: list[str]) -> int:
    """1 only when messages were due and none was accepted (so the next run retries); 0 otherwise."""
    if statuses and not any(s in ("DELIVERED", "UNCONFIRMED") for s in statuses):
        return 1
    return 0


def send_in_order(texts: list[str], deliver) -> list[str]:
    """Send in order and stop at the first message Telegram did not accept (a later one is not sent)."""
    statuses: list[str] = []
    for text in texts:
        statuses.append(deliver(text))
        if statuses[-1] not in ("DELIVERED", "UNCONFIRMED"):
            break
    return statuses
