"""Stateless dedupe: "what is new since the last successful run" from the run history, not stored state.

Owner and audit (RELEASE GATE): dedupe state derived from restricted data is not kept anywhere public,
and the standing gate keeps Alpaca-key workflows off actions/cache. So each run asks GitHub when this
workflow last ran successfully today (operational metadata, already public) and recomputes, from the
source data at run time, what changed after that moment. Nothing about any alert is stored.

Failure semantics: a run that delivered nothing because Telegram refused exits non-zero, so the next run
still measures from the last successful run and resends it while valid; a run that delivered something
exits 0 (a later message's failure is then lost, never duplicated). UNCONFIRMED counts as delivered.
If the history cannot be read, callers send no event alerts and exit non-zero, so that run never
becomes the next run's baseline (a successful run that processed nothing would hide its window).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests

API = "https://api.github.com"


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _get(http: Any, env: dict[str, str], path: str, params: dict | None = None) -> Any:
    repo, token = env.get("GITHUB_REPOSITORY"), env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    if not repo or not token:
        return None
    try:
        r = http.get(f"{API}/repos/{repo}{path}", params=params or {}, timeout=15,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def step_time(env: dict[str, str], run_id: Any, step: str, mark: str = "started_at", *,
              http: Any = requests) -> datetime | None:
    """When a named step of a run started (or completed): the moment the run actually processed data."""
    body = _get(http, env, f"/actions/runs/{run_id}/jobs")
    for job in (body or {}).get("jobs") or []:
        for st in job.get("steps") or []:
            if st.get("name") == step:
                return _ts(st.get(mark))
    return None


def previous_success(env: dict[str, str], workflow: str, now: datetime, *, day_start: datetime,
                     http: Any = requests, step: str | None = None,
                     mark: str = "started_at") -> tuple[str, datetime | None]:
    """("OK", t) for the latest successful run today other than this one; ("NONE_TODAY", None); ("UNKNOWN", None).

    t is the run's start, or - when `step` is named - that step's start/completion, so both window edges
    are measured from the same processing moment (audit: a run's start is not when it read the data).
    A step time that cannot be read falls back to the run's own times: started_at -> run start (earlier,
    so a boundary event may repeat), completed_at -> run update time (later, so it may be missed).
    """
    body = _get(http, env, f"/actions/workflows/{workflow}/runs",
                {"status": "success", "per_page": 20, "created": f">={day_start.date().isoformat()}"})
    if body is None:
        return "UNKNOWN", None
    this = str(env.get("GITHUB_RUN_ID") or "")
    best = None
    for run in body.get("workflow_runs") or []:
        if str(run.get("id")) == this or run.get("event") == "push":
            continue
        t = _ts(run.get("run_started_at") or run.get("created_at"))
        if t and day_start <= t < now and (best is None or t > best[0]):
            best = (t, run)
    if best is None:
        return "NONE_TODAY", None
    if not step:
        return "OK", best[0]
    fallback = best[0] if mark == "started_at" else (_ts(best[1].get("updated_at")) or best[0])
    return "OK", step_time(env, best[1].get("id"), step, mark, http=http) or fallback


def own_step_time(env: dict[str, str], step: str, now: datetime, *, http: Any = requests) -> datetime:
    """This run's processing-step start (the same edge previous_success reads for the next run)."""
    return step_time(env, env.get("GITHUB_RUN_ID"), step, "started_at", http=http) or now


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
