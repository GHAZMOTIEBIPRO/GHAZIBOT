"""Workflow hardening guards (2026-11-19): the token is not persisted where git is not used, PR runs get no
secrets, PR-triggered upstreams cannot drive privileged workflow_run consumers, and write scopes are needed."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
GIT_NET = re.compile(r"\bgit\b[^\n]*\b(push|pull|fetch|clone|ls-remote)\b")
DURABLE = ("run_adaptive_learning", "run_stock_outcome_audit", "enrich_stock_radar_research",
           "run_options_radar_fabric", "durable_state", "durable_stock_state")


def _load(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def _job_text(job: dict) -> str:
    parts = []
    for step in job.get("steps", []):
        parts.append(str(step.get("run") or ""))
        uses = str(step.get("uses") or "")
        local = ROOT / uses.lstrip("./") / "action.yml"
        if uses.startswith("./") and local.exists():
            parts.append(local.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_checkouts_keep_the_token_only_in_jobs_that_use_git_over_the_network():
    leaking = []
    for path in WORKFLOWS:
        spec, _ = _load(path)
        for name, job in (spec.get("jobs") or {}).items():
            text = _job_text(job)
            uses_git = bool(GIT_NET.search(text)) or any(s in text for s in DURABLE)
            for step in job.get("steps", []):
                is_checkout = str(step.get("uses", "")).startswith("actions/checkout@")
                if is_checkout and not uses_git and (step.get("with") or {}).get("persist-credentials") is not False:
                    leaking.append(f"{path.name}:{name}")
    assert leaking == []


def test_pull_request_runs_receive_no_secrets():
    for path in WORKFLOWS:
        spec, text = _load(path)
        on = spec.get(True) or {}
        if not (isinstance(on, dict) and "pull_request" in on):
            continue
        for expr in re.findall(r"\$\{\{([^}]*secrets\.[^}]*)\}\}", text):
            assert "github.event_name != 'pull_request' && secrets." in expr, (path.name, expr.strip())


def test_no_pull_request_target_and_pr_upstreams_are_repository_guarded():
    names = {}
    pr_triggered = set()
    for path in WORKFLOWS:
        spec, _ = _load(path)
        names[spec.get("name")] = path.name
        on = spec.get(True) or {}
        assert not (isinstance(on, dict) and "pull_request_target" in on), path.name
        if isinstance(on, dict) and "pull_request" in on:
            pr_triggered.add(path.name)
    for path in WORKFLOWS:
        spec, text = _load(path)
        on = spec.get(True) or {}
        if not (isinstance(on, dict) and "workflow_run" in on):
            continue
        upstream = {names.get(w) for w in (on["workflow_run"] or {}).get("workflows") or []}
        if upstream & pr_triggered:
            assert "github.event.workflow_run.head_repository.full_name == github.repository" in text, path.name
            assert "github.event.workflow_run.event != 'pull_request'" in text, path.name


def test_workflow_level_contents_write_is_used_by_a_pushing_job():
    for path in WORKFLOWS:
        spec, _ = _load(path)
        perms = spec.get("permissions") or {}
        if not isinstance(perms, dict) or perms.get("contents") != "write":
            continue
        jobs = [j for j in (spec.get("jobs") or {}).values() if "permissions" not in j]
        pushing = [j for j in jobs if re.search(r"git\b[^\n]*\bpush\b", _job_text(j))]
        assert pushing, f"{path.name}: contents:write but no job pushes"
