from pathlib import Path

import yaml

CORE_CHILDREN = (
    "fast-explosion-radar.yml",
    "classical-direction-radar.yml",
    "company-news-watch.yml",
    "free-data-health.yml",
    "free-gex-validation.yml",
    "options-contract-radar.yml",
    "options-radar.yml",
    "adaptive-review.yml",
    "spx-dashboard.yml",
)


def _workflow(name: str) -> str:
    return Path(".github/workflows", name).read_text(encoding="utf-8")


def test_market_orchestrator_owns_core_cadence():
    text = _workflow("market-orchestrator.yml")
    assert "schedule:" in text
    assert 'cron: "2-57/5 8-23 * * 1-5"' in text
    assert "actions: write" in text
    assert "gh workflow run" in text
    assert "age_minutes()" in text
    assert "GH_TOKEN: ${{ github.token }}" in text


def test_core_children_are_dispatchable_but_not_independently_scheduled():
    for name in CORE_CHILDREN:
        text = _workflow(name)
        assert "workflow_dispatch:" in text, name
        assert "schedule:" not in text, name


def test_paid_realtime_options_is_manual_only_under_zero_cost_policy():
    text = _workflow("options-realtime-intelligence-v9.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "INTRINIO_API_KEY" in text


def test_legacy_cadence_watchdog_is_manual_only():
    text = _workflow("omega-cadence-watchdog.yml")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "GH_TOKEN: ${{ github.token }}" in text


def test_existing_orchestrator_can_rescue_missing_cron_from_independent_news_flash():
    central = _workflow("market-orchestrator.yml")
    flash = _workflow("news-flash-24x7.yml")
    # News Flash has a separate schedule and is not dispatched by the owner.
    assert "schedule:" in flash
    assert 'workflows: ["BLACK BOX News Flash 24x7"]' in central
    assert "workflow_run:" in central
    assert "branches: [main]" in central
    assert "types: [completed]" in central
    assert "github.event.workflow_run.conclusion == 'success'" in central
    # Child scanning cadence stays centralized; do not add a second dispatcher.
    assert central.count("dispatch_if_stale fast-explosion-radar.yml") == 1
    assert "cancel-in-progress: false" in central


def test_orchestrator_deployment_has_safe_bootstrap_and_diagnostics():
    central = _workflow("market-orchestrator.yml")
    assert 'cron: "2-57/5 8-23 * * 1-5"' in central
    assert ".github/workflows/market-orchestrator.yml" in central
    assert "Last scheduled Market Orchestrator run age" in central
    assert "No recent central scheduler run" in central
    assert "age=${age}m" in central
    assert r"age=\\${age}m" not in central
    assert "gh workflow run" in central


def test_any_wakeup_keeps_bounded_five_minute_cadence_with_relay():
    central = _workflow("market-orchestrator.yml")
    spec = yaml.safe_load(central)
    job = spec["jobs"]["dispatch"]
    # GitHub delivers few crons; a wakeup loops ~50 min inside the timeout.
    assert job["timeout-minutes"] <= 60
    step = next(s for s in job["steps"]
                if s.get("name", "").startswith("Dispatch stale market engines"))
    passes = step["env"]["ORCHESTRATOR_PASSES"]
    assert "'10'" in passes and "'1'" in passes
    body = step["run"]
    assert "sleep 300" in body
    assert "python3 scripts/relay_dependent_workflows.py" in body
    assert "utc_hour < 8 || utc_hour > 23" in body
    # A failed pass warns instead of ending the cadence loop.
    assert "dispatch_pass || echo" in body
    assert 10 * 5 < job["timeout-minutes"]


def test_looping_run_chains_its_successor_within_weekday_market_window():
    spec = yaml.safe_load(_workflow("market-orchestrator.yml"))
    on = spec.get(True) or spec.get("on")
    assert on["workflow_dispatch"]["inputs"]["chain"]["type"] == "boolean"
    job = spec["jobs"]["dispatch"]
    step = next(s for s in job["steps"]
                if s.get("name", "").startswith("Dispatch stale market engines"))
    assert "inputs.chain" in step["env"]["ORCHESTRATOR_PASSES"]
    assert "vars.ORCHESTRATOR_SELF_CHAIN" in step["env"]["ORCHESTRATOR_SELF_CHAIN"]
    body = step["run"]
    assert "gh workflow run market-orchestrator.yml" in body and "-f chain=true" in body
    # Only looping runs chain, only on weekdays 08-22 UTC, with a kill switch.
    assert "(( passes > 1 ))" in body
    assert "$(date -u +%u) <= 5 && end_hour >= 8 && end_hour <= 22" in body
    assert '"${ORCHESTRATOR_SELF_CHAIN:-true}" != "false"' in body
    # Weekends get a single pass per wakeup.
    assert "$(date -u +%u) > 5" in body
    # One running + one pending: chained runs never cancel an active pass.
    assert spec["concurrency"]["cancel-in-progress"] is False


def test_pre_market_wakeup_bridges_to_the_08_utc_start_with_a_bounded_wait():
    spec = yaml.safe_load(_workflow("market-orchestrator.yml"))
    dispatch = spec["jobs"]["dispatch"]
    assert dispatch["timeout-minutes"] == 58
    assert dispatch["outputs"]["bridge_seconds"] == "${{ steps.cadence.outputs.bridge_seconds }}"
    body = next(s for s in dispatch["steps"] if s.get("id") == "cadence")["run"]
    # Only looping wakeups, weekdays, before 08:00 and at most 5h50m away.
    assert "wait_s > 0 && wait_s <= 21000" in body
    assert "date -u -d 'today 08:00' +%s" in body
    bridge = spec["jobs"]["bridge"]
    assert bridge["needs"] == "dispatch"
    assert bridge["if"] == "needs.dispatch.outputs.bridge_seconds != ''"
    assert bridge["timeout-minutes"] == 360
    run = bridge["steps"][0]["run"]
    assert "(( BRIDGE_SECONDS <= 21000 ))" in run
    assert "gh workflow run market-orchestrator.yml" in run and "-f chain=true" in run
