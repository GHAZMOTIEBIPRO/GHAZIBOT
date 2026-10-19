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
