from __future__ import annotations

from pathlib import Path


def test_dashboard_reads_durable_runtime_before_main_fallback() -> None:
    source = Path("public/app.js").read_text(encoding="utf-8")
    durable = "GHAZIBOT/bot-state/runtime/public/data/latest.json"
    legacy = "GHAZIBOT/main/public/data/latest.json"
    assert durable in source
    assert legacy in source
    assert source.index(durable) < source.index(legacy)


def test_research_workflow_restores_and_persists_bot_state_without_main_data_commit() -> None:
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert "runtime_state_vault restore" in workflow
    assert "runtime_state_vault publish" in workflow
    assert "HEAD:bot-state" in workflow
    assert "data: refresh GHAZIBOT Omega research state" not in workflow
    assert "git push origin HEAD:main" not in workflow
    assert "git -C .bot-state add runtime" in workflow


def test_runtime_state_migration_keeps_artifact_backup() -> None:
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert "ghazibot-omega-results" in workflow
    assert "public/data/latest.json" in workflow
    assert "data/live/*.json" in workflow


def test_spx_and_free_health_publish_runtime_to_bot_state_not_main() -> None:
    spx = Path(".github/workflows/spx-dashboard.yml").read_text(encoding="utf-8")
    health = Path(".github/workflows/free-data-health.yml").read_text(encoding="utf-8")
    assert "HEAD:main" not in spx
    assert "origin main" not in spx
    assert "HEAD:main" not in health
    assert "origin main" not in health
    assert "origin bot-state" in spx
    assert "origin bot-state" in health
    assert "runtime/public/data/spx_dashboard.json" in spx
    assert "runtime/public/data/free_data_health.json" in health


def test_spx_ui_prefers_durable_runtime_state() -> None:
    source = Path("public/spx/spx.js").read_text(encoding="utf-8")
    durable = "GHAZIBOT/bot-state/runtime/public/data/"
    assert durable in source
    assert "spx_dashboard.json" in source
    assert "free_data_health.json" in source


def test_free_gex_validation_is_shadow_tolerant_and_publishes_to_bot_state() -> None:
    workflow = Path(".github/workflows/free-gex-validation.yml").read_text(encoding="utf-8")
    assert 'engine["available"] is True' not in workflow
    assert "staying SHADOW_ONLY without failing the workflow" in workflow
    assert "HEAD:main" not in workflow
    assert "origin main" not in workflow
    assert "origin bot-state" in workflow
    assert "runtime/public/data/free_gex_validation.json" in workflow


def test_spx_ui_prefers_durable_free_gex_validation() -> None:
    source = Path("public/spx/spx.js").read_text(encoding="utf-8")
    assert "DURABLE+'free_gex_validation.json'" in source


def test_general_runtime_vault_does_not_own_dedicated_runtime_feeds() -> None:
    source = Path("scripts/runtime_state_vault.py").read_text(encoding="utf-8")
    assert '"public/data/spx_dashboard.json"' not in source
    assert '"public/data/free_data_health.json"' not in source
    assert '"public/data/free_gex_validation.json"' not in source
    assert '"public/data/free_gex_validation_history.json"' not in source


def test_omega_runtime_publish_rebuilds_from_latest_bot_state_on_contention() -> None:
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert "git -C .bot-state reset --hard origin/bot-state" in workflow
    assert "for attempt in 1 2 3 4" in workflow
    assert "pull --rebase origin bot-state" not in workflow
