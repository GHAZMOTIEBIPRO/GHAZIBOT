"""Relay completed source runs to their dependent stages.

GitHub does not raise ``workflow_run`` events for runs started with the
workflow's own GITHUB_TOKEN. The Market Orchestrator dispatches every core
radar that way, so dependent stages (state vaults, cross-confirmation,
research enrichment, walk-forward, live status) only ever ran after human
pushes. This relay, owned by the orchestrator, dispatches each dependent
stage in its existing ``workflow_dispatch`` mode once per completed source
run. Dependents already resolve the latest successful source artifact in
that mode, so no stage logic or state writer changes.

Guards: a grace period lets a normal ``workflow_run`` win (no duplicate),
ancient runs are never relayed, a source without its validated artifact is
skipped, and each target is dispatched at most once per tick so a
concurrency group never drops a pending run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

GRACE_MINUTES = 3.0
MAX_SOURCE_AGE_MINUTES = 180.0
LIVE_STATUS = "live-dashboard-status.yml"
STOCK_VAULT = "stock-state-vault.yml"
STRENGTH = "site-evidence-strength.yml"


@dataclass(frozen=True)
class Target:
    workflow: str
    inputs: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> str:
        """Runs of targets with inputs are titled '... · <value>' (run-name)."""
        return self.workflow + "".join(f"|{v}" for _, v in self.inputs)


@dataclass(frozen=True)
class Relay:
    source: str
    artifact: str | None
    targets: tuple[Target, ...] = field(default_factory=tuple)


RELAYS: tuple[Relay, ...] = (
    Relay("fast-explosion-radar.yml", "fast-market-state", (
        Target("explosion-options-crosscheck.yml"),
        Target(LIVE_STATUS, (("source_workflow", "fast-explosion-radar.yml"),)),
    )),
    Relay("stock-radar.yml", "independent-stock-radar", (
        Target(STOCK_VAULT, (("source_kind", "stock"),)),
        Target("cross-confirmation.yml"),
        Target(LIVE_STATUS, (("source_workflow", "stock-radar.yml"),)),
    )),
    Relay("options-contract-radar.yml", "independent-options-radar", (
        Target("options-research-enrichment.yml"),
        Target("options-state-vault.yml"),
        Target("cross-confirmation.yml"),
        Target(LIVE_STATUS, (("source_workflow", "options-contract-radar.yml"),)),
    )),
    Relay("stock-outcome-auditor.yml", "stock-outcome-audit-state", (
        Target("stock-walk-forward.yml"),
        Target(STOCK_VAULT, (("source_kind", "audit"),)),
    )),
    Relay("adaptive-review.yml", "adaptive-learning-state", (
        Target(STOCK_VAULT, (("source_kind", "adaptive"),)),
    )),
    Relay("stock-walk-forward.yml", "stock-walk-forward-state", (
        Target(STRENGTH),
    )),
    # Index research publishes straight to bot-state (no artifact).
    Relay("index-radar.yml", None, (
        Target("stock-watch-charts.yml"),
    )),
    # Charts publish straight to bot-state as well.
    Relay("stock-watch-charts.yml", None, (
        Target(STRENGTH),
    )),
)


WATCHDOG = "telegram-failure-watchdog.yml"
# Core engines whose failures (and recoveries) must reach Telegram even when
# the orchestrator, not a human push, started them.
WATCHED_SOURCES: tuple[str, ...] = (
    "fast-explosion-radar.yml",
    "stock-radar.yml",
    "options-contract-radar.yml",
    "classical-direction-radar.yml",
)
FAILURES = frozenset({"failure", "timed_out", "action_required", "startup_failure"})


def _parse(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else None


def plan_dispatches(
    *,
    now: datetime,
    source_runs: dict[str, dict[str, Any]],
    artifacts: dict[str, bool],
    target_last_created: dict[str, datetime | None],
    relays: tuple[Relay, ...] = RELAYS,
) -> list[dict[str, Any]]:
    """Pure decision: which dependent stages to dispatch on this tick.

    ``source_runs[source]`` is the latest *successful* main run (``id``,
    ``updated_at``); ``artifacts[source]`` says its required artifact exists;
    ``target_last_created[target.key]`` is that target's newest run start.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    planned: dict[str, dict[str, Any]] = {}
    for relay in relays:
        run = source_runs.get(relay.source) or {}
        finished = _parse(run.get("updated_at"))
        if finished is None:
            continue
        age = (now - finished).total_seconds() / 60.0
        if age < GRACE_MINUTES or age > MAX_SOURCE_AGE_MINUTES:
            continue
        if relay.artifact and not artifacts.get(relay.source):
            continue
        for target in relay.targets:
            last = target_last_created.get(target.key)
            if last is not None and last >= finished:
                continue
            # One dispatch per workflow per tick; the oldest-lagging wins.
            current = planned.get(target.workflow)
            if current is None or finished < current["_finished"]:
                planned[target.workflow] = {
                    "workflow": target.workflow,
                    "inputs": dict(target.inputs),
                    "source": relay.source,
                    "source_run_id": run.get("id"),
                    "_finished": finished,
                }
    return [
        {k: v for k, v in item.items() if k != "_finished"}
        for item in sorted(planned.values(), key=lambda x: x["workflow"])
    ]


def plan_watchdog(
    *,
    now: datetime,
    completed: dict[str, list[dict[str, Any]]],
    watchdog_titles: list[str],
) -> dict[str, Any] | None:
    """At most one watchdog dispatch per tick: the oldest unreported failure
    or failure->success recovery among the watched engines.

    ``completed[source]`` lists that engine's newest completed main runs
    (``id``, ``conclusion``, ``updated_at``), newest first. A run whose id
    already appears in a watchdog run title was reported (relay or a genuine
    workflow_run) and is skipped. Consecutive-failure dedup and stale-event
    filtering stay inside the watchdog's own classifier.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    best: tuple[datetime, dict[str, Any]] | None = None
    for source in WATCHED_SOURCES:
        rows = completed.get(source) or []
        if not rows:
            continue
        latest = rows[0]
        finished = _parse(latest.get("updated_at"))
        run_id = str(latest.get("id") or "")
        if finished is None or not run_id.isdigit():
            continue
        age = (now - finished).total_seconds() / 60.0
        if age < GRACE_MINUTES or age > MAX_SOURCE_AGE_MINUTES:
            continue
        conclusion = str(latest.get("conclusion") or "")
        previous = str(rows[1].get("conclusion") or "") if len(rows) > 1 else ""
        if not (conclusion in FAILURES or (conclusion == "success" and previous in FAILURES)):
            continue
        if any(run_id in str(title) for title in watchdog_titles):
            continue
        item = {"workflow": WATCHDOG, "inputs": {"source_run_id": run_id},
                "source": source, "source_run_id": int(run_id), "kind": conclusion}
        if best is None or finished < best[0]:
            best = (finished, item)
    return best[1] if best else None


def _gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, timeout=60,
    ).stdout


def _latest_success(repo: str, workflow: str) -> dict[str, Any]:
    out = _gh(["run", "list", "--repo", repo, "--workflow", workflow,
               "--status", "success", "--branch", "main", "--limit", "1",
               "--json", "databaseId,updatedAt"])
    rows = json.loads(out or "[]")
    if not rows:
        return {}
    return {"id": rows[0].get("databaseId"), "updated_at": rows[0].get("updatedAt")}


def _has_artifact(repo: str, run_id: Any, name: str) -> bool:
    out = _gh(["api", f"repos/{repo}/actions/runs/{int(run_id)}/artifacts",
               "--jq", f'[.artifacts[] | select(.name == "{name}" and .expired == false)] | length'])
    return out.strip().isdigit() and int(out.strip()) > 0


def _last_created(repo: str, target: Target) -> datetime | None:
    out = _gh(["run", "list", "--repo", repo, "--workflow", target.workflow,
               "--branch", "main", "--limit", "20",
               "--json", "createdAt,displayTitle"])
    for row in json.loads(out or "[]"):
        # Titles of targets with inputs end in '· <value>' (see run-name).
        if target.inputs and not all(f"· {v}" in str(row.get("displayTitle") or "")
                                     for _, v in target.inputs):
            continue
        return _parse(row.get("createdAt"))
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    source_runs: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, bool] = {}
    last: dict[str, datetime | None] = {}
    for relay in RELAYS:
        try:
            run = _latest_success(args.repo, relay.source)
            source_runs[relay.source] = run
            artifacts[relay.source] = bool(
                run.get("id") and relay.artifact
                and _has_artifact(args.repo, run["id"], relay.artifact))
            for target in relay.targets:
                if target.key not in last:
                    last[target.key] = _last_created(args.repo, target)
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            # One unreadable source never blocks the others.
            print(f"relay: skip {relay.source}: {type(exc).__name__}")
    plan = plan_dispatches(now=now, source_runs=source_runs,
                           artifacts=artifacts, target_last_created=last)
    try:
        completed = {}
        for source in WATCHED_SOURCES:
            out = _gh(["run", "list", "--repo", args.repo, "--workflow", source,
                       "--status", "completed", "--branch", "main", "--limit", "2",
                       "--json", "databaseId,conclusion,updatedAt"])
            completed[source] = [
                {"id": row.get("databaseId"), "conclusion": row.get("conclusion"),
                 "updated_at": row.get("updatedAt")}
                for row in json.loads(out or "[]")]
        titles = [str(row.get("displayTitle") or "") for row in json.loads(_gh([
            "run", "list", "--repo", args.repo, "--workflow", WATCHDOG,
            "--limit", "40", "--json", "displayTitle"]) or "[]")]
        alert = plan_watchdog(now=now, completed=completed, watchdog_titles=titles)
        if alert:
            plan.append(alert)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        print(f"relay: watchdog check skipped: {type(exc).__name__}")
    if not plan:
        print("relay: every dependent stage is current")
    for item in plan:
        print(f"relay: {item['source']} run {item['source_run_id']} -> {item['workflow']} {item['inputs']}")
        if args.dry_run:
            continue
        cmd = ["workflow", "run", item["workflow"], "--repo", args.repo, "--ref", "main"]
        for key, value in item["inputs"].items():
            cmd += ["-f", f"{key}={value}"]
        try:
            _gh(cmd)
        except subprocess.SubprocessError as exc:
            print(f"::warning title=Relay dispatch failed::{item['workflow']}: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
