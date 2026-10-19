"""Orchestrator relay: dependents of GITHUB_TOKEN-dispatched runs still run."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts.relay_dependent_workflows import (
    LIVE_STATUS,
    RELAYS,
    STOCK_VAULT,
    STRENGTH,
    Target,
    plan_dispatches,
)

NOW = datetime(2026, 10, 19, 17, 0, tzinfo=timezone.utc)


def _iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def _stamp(minutes_ago: float) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def _plan(source_runs, artifacts=None, last=None):
    return plan_dispatches(
        now=NOW,
        source_runs=source_runs,
        artifacts=artifacts if artifacts is not None else dict.fromkeys(source_runs, True),
        target_last_created=last or {},
    )


def test_completed_options_run_relays_every_dependent_once():
    plan = _plan({"options-contract-radar.yml": {"id": 7, "updated_at": _iso(10)}})
    workflows = [item["workflow"] for item in plan]
    assert workflows == sorted({
        "options-research-enrichment.yml", "options-state-vault.yml",
        "cross-confirmation.yml", LIVE_STATUS,
    })
    live = next(item for item in plan if item["workflow"] == LIVE_STATUS)
    assert live["inputs"] == {"source_workflow": "options-contract-radar.yml"}
    assert all(item["source_run_id"] == 7 for item in plan)


def test_already_relayed_or_workflow_run_triggered_dependents_are_skipped():
    runs = {"stock-radar.yml": {"id": 3, "updated_at": _iso(20)}}
    last = {
        Target(STOCK_VAULT, (("source_kind", "stock"),)).key: _stamp(19),
        "cross-confirmation.yml": _stamp(19),
        Target(LIVE_STATUS, (("source_workflow", "stock-radar.yml"),)).key: _stamp(30),
    }
    plan = _plan(runs, last=last)
    assert [item["workflow"] for item in plan] == [LIVE_STATUS]


def test_grace_period_age_limit_and_missing_artifact_block_relay():
    assert _plan({"stock-radar.yml": {"id": 1, "updated_at": _iso(1)}}) == []
    assert _plan({"stock-radar.yml": {"id": 1, "updated_at": _iso(400)}}) == []
    assert _plan({"stock-radar.yml": {"id": 1, "updated_at": _iso(10)}},
                 artifacts={"stock-radar.yml": False}) == []
    assert _plan({"stock-radar.yml": {"id": 1, "updated_at": "not-a-time"}}) == []
    assert _plan({}) == []


def test_each_target_is_dispatched_at_most_once_per_tick_oldest_source_first():
    plan = _plan({
        "fast-explosion-radar.yml": {"id": 1, "updated_at": _iso(40)},
        "stock-radar.yml": {"id": 2, "updated_at": _iso(20)},
        "options-contract-radar.yml": {"id": 3, "updated_at": _iso(10)},
    })
    workflows = [item["workflow"] for item in plan]
    assert len(workflows) == len(set(workflows))
    live = next(item for item in plan if item["workflow"] == LIVE_STATUS)
    assert live["inputs"] == {"source_workflow": "fast-explosion-radar.yml"}
    cross = next(item for item in plan if item["workflow"] == "cross-confirmation.yml")
    assert cross["source"] == "stock-radar.yml"


def test_auditor_relays_walk_forward_and_its_vault_persistence():
    plan = _plan({"stock-outcome-auditor.yml": {"id": 9, "updated_at": _iso(5)}})
    assert [(item["workflow"], item["inputs"]) for item in plan] == [
        (STOCK_VAULT, {"source_kind": "audit"}),
        ("stock-walk-forward.yml", {}),
    ]


def test_adaptive_review_is_persisted_by_the_stock_vault():
    plan = _plan({"adaptive-review.yml": {"id": 5, "updated_at": _iso(8)}})
    assert plan == [{"workflow": STOCK_VAULT, "inputs": {"source_kind": "adaptive"},
                     "source": "adaptive-review.yml", "source_run_id": 5}]
    done = {Target(STOCK_VAULT, (("source_kind", "adaptive"),)).key: _stamp(4)}
    assert _plan({"adaptive-review.yml": {"id": 5, "updated_at": _iso(8)}}, last=done) == []


def test_vault_kinds_share_one_dispatch_per_tick_oldest_first():
    plan = _plan({
        "stock-radar.yml": {"id": 1, "updated_at": _iso(10)},
        "adaptive-review.yml": {"id": 2, "updated_at": _iso(30)},
        "stock-outcome-auditor.yml": {"id": 3, "updated_at": _iso(20)},
    })
    vault = [item for item in plan if item["workflow"] == STOCK_VAULT]
    assert vault == [{"workflow": STOCK_VAULT, "inputs": {"source_kind": "adaptive"},
                      "source": "adaptive-review.yml", "source_run_id": 2}]


def test_strength_score_refreshes_after_charts_or_walk_forward():
    charts = _plan({"stock-watch-charts.yml": {"id": 6, "updated_at": _iso(5)}},
                   artifacts={"stock-watch-charts.yml": False})
    assert [item["workflow"] for item in charts] == [STRENGTH]
    walk = _plan({"stock-walk-forward.yml": {"id": 7, "updated_at": _iso(5)}})
    assert [item["workflow"] for item in walk] == [STRENGTH]
    assert _plan({"stock-walk-forward.yml": {"id": 7, "updated_at": _iso(5)}},
                 last={STRENGTH: _stamp(2)}) == []


def test_vault_titles_name_their_kind_for_relay_dedup():
    vault = Path(".github/workflows/stock-state-vault.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(vault)
    title = " ".join(spec["run-name"].split())
    assert title.startswith("Durable Stock Evidence Vault · ${{ inputs.source_kind")
    assert "'BLACK BOX Omega Adaptive Evidence Review' && 'adaptive'" in title
    assert "'BLACK BOX Omega Stock Outcome Auditor' && 'audit'" in title
    for kind, source in (("adaptive", "adaptive-review.yml"),
                         ("audit", "stock-outcome-auditor.yml"),
                         ("stock", "stock-radar.yml")):
        assert f"{kind}) kind={kind}; source_workflow={source}" in vault or (
            kind == "stock" and f"*) kind=stock; source_workflow={source}" in vault)


def test_naive_now_is_rejected():
    try:
        plan_dispatches(now=NOW.replace(tzinfo=None), source_runs={},
                        artifacts={}, target_last_created={})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_every_relay_target_accepts_workflow_dispatch_with_declared_inputs():
    root = Path(".github/workflows")
    for relay in RELAYS:
        assert (root / relay.source).is_file(), relay.source
        for target in relay.targets:
            spec = yaml.safe_load((root / target.workflow).read_text(encoding="utf-8"))
            on = spec.get(True) or spec.get("on")
            assert "workflow_dispatch" in on, target.workflow
            declared = (on["workflow_dispatch"] or {}).get("inputs") or {}
            for name, value in target.inputs:
                assert name in declared, (target.workflow, name)
                options = declared[name].get("options")
                assert options is None or value in options


def test_orchestrator_owns_relay_and_live_status_titles_name_their_source():
    central = Path(".github/workflows/market-orchestrator.yml").read_text(encoding="utf-8")
    assert "python3 scripts/relay_dependent_workflows.py" in central
    assert "sparse-checkout: scripts/relay_dependent_workflows.py" in central
    live = Path(".github/workflows/live-dashboard-status.yml").read_text(encoding="utf-8")
    assert "inputs.source_workflow || github.event.workflow_run.path" in live


def test_index_research_relays_stock_charts_without_an_artifact():
    plan = _plan({"index-radar.yml": {"id": 4, "updated_at": _iso(6)}},
                 artifacts={"index-radar.yml": False})
    assert [item["workflow"] for item in plan] == ["stock-watch-charts.yml"]


def test_index_radar_cadence_is_owned_by_the_orchestrator():
    central = Path(".github/workflows/market-orchestrator.yml").read_text(encoding="utf-8")
    index = Path(".github/workflows/index-radar.yml").read_text(encoding="utf-8")
    assert central.count("dispatch_if_stale index-radar.yml") == 1
    assert "schedule:" not in index and "workflow_dispatch:" in index


def _runs(*pairs):
    return [{"id": rid, "conclusion": c, "updated_at": _iso(age)} for rid, c, age in pairs]


def test_watchdog_relays_one_unreported_failure_per_tick_oldest_first():
    from scripts.relay_dependent_workflows import WATCHDOG, plan_watchdog

    item = plan_watchdog(now=NOW, watchdog_titles=[], completed={
        "stock-radar.yml": _runs((11, "failure", 10)),
        "options-contract-radar.yml": _runs((22, "timed_out", 30)),
    })
    assert item["workflow"] == WATCHDOG
    assert item["inputs"] == {"source_run_id": "22"}
    # Already reported (relay title or a genuine workflow_run title).
    again = plan_watchdog(now=NOW, watchdog_titles=["Telegram Failure Watchdog · 22"],
                          completed={"options-contract-radar.yml": _runs((22, "failure", 30))})
    assert again is None


def test_watchdog_relays_recovery_but_not_plain_success_or_stale_or_cancelled():
    from scripts.relay_dependent_workflows import plan_watchdog

    def plan(rows):
        return plan_watchdog(now=NOW, watchdog_titles=[], completed={"fast-explosion-radar.yml": rows})

    assert plan(_runs((5, "success", 10), (4, "failure", 30)))["inputs"] == {"source_run_id": "5"}
    assert plan(_runs((5, "success", 10), (4, "success", 30))) is None
    assert plan(_runs((5, "cancelled", 10))) is None
    assert plan(_runs((5, "failure", 1))) is None      # grace period
    assert plan(_runs((5, "failure", 400))) is None    # too old
    assert plan([]) is None


def test_watchdog_accepts_relayed_run_id_and_titles_it():
    spec = yaml.safe_load(Path(".github/workflows/telegram-failure-watchdog.yml").read_text(encoding="utf-8"))
    on = spec.get(True) or spec.get("on")
    assert "source_run_id" in on["workflow_dispatch"]["inputs"]
    assert "inputs.source_run_id || github.event.workflow_run.id" in spec["run-name"]
    env = spec["jobs"]["notify-failure"]["env"]
    assert env["WATCHDOG_SOURCE_RUN_ID"] == "${{ inputs.source_run_id || '' }}"


def test_relayed_walk_forward_reads_newest_audit_artifact_before_bot_state():
    walk = Path(".github/workflows/stock-walk-forward.yml").read_text(encoding="utf-8")
    artifact = walk.index("gh run list --workflow stock-outcome-auditor.yml --status success")
    fallback = walk.index("git show origin/bot-state:state/stocks/stock_outcome_audit.json")
    assert artifact < fallback
    assert "actions: read" in walk
