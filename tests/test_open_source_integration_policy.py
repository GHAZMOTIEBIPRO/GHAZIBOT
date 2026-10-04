import json
from pathlib import Path


def test_open_source_registry_has_explicit_license_and_authority_policy():
    payload = json.loads(Path("research/external_open_source_integrations.json").read_text(encoding="utf-8"))
    assert payload["policy"]["zero_cost"] is True
    assert payload["policy"]["external_source_does_not_gain_independence_by_brand_name"] is True
    projects = {row["repo"]: row for row in payload["projects"]}
    assert projects["dpguthrie/yahooquery"]["counts_as_independent_source"] is False
    assert projects["marcdemers/py_vollib_vectorized"]["live_decision_authority"] is False
    assert projects["kernc/backtesting.py"]["decision"] == "NO_CODE_MERGE"


def test_open_source_greeks_validator_is_shadow_only():
    source = Path("scripts/validate_open_source_greeks.py").read_text(encoding="utf-8")
    assert '"mode": "SHADOW_VALIDATION"' in source
    assert '"decision_authority": False' in source
    assert "py_vollib_vectorized" in source
    assert "py_vollib" in source


def test_research_dependencies_are_not_in_realtime_paid_runtime():
    research = Path("requirements-research.txt").read_text(encoding="utf-8")
    realtime = Path("requirements-realtime.txt").read_text(encoding="utf-8")
    assert "py_vollib" in research
    assert "py_vollib_vectorized" in research
    assert "py_vollib" not in realtime


def test_open_source_validation_workflow_is_weekly_or_manual_not_market_critical():
    text = Path(".github/workflows/open-source-model-validation.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text
    assert 'cron: "40 9 * * 0"' in text
    assert "python -m scripts.validate_open_source_greeks" in text
    assert "ref: main" not in text
    assert "open-source-model-validation" in text
