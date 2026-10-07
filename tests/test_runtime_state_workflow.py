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
    assert '"public/data/live_dashboard_status.json"' not in source


def test_live_dashboard_status_has_one_bot_state_writer() -> None:
    general = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    dedicated = Path(".github/workflows/live-dashboard-status.yml").read_text(encoding="utf-8")
    vault = Path("scripts/runtime_state_vault.py").read_text(encoding="utf-8")

    assert "runtime_state_vault publish" in general
    assert '"public/data/live_dashboard_status.json"' not in vault
    assert "runtime/public/data/live_dashboard_status.json" in dedicated or "git add runtime/" in dedicated
    assert "BLACK BOX Omega Dashboard State" in dedicated


def test_omega_runtime_publish_rebuilds_from_latest_bot_state_on_contention() -> None:
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert "git -C .bot-state reset --hard origin/bot-state" in workflow
    assert "for attempt in 1 2 3 4" in workflow
    assert "pull --rebase origin bot-state" not in workflow


def test_omega_target_learning_is_durable_and_non_blocking() -> None:
    vault = Path("scripts/runtime_state_vault.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert '"data/live/omega_target_state.json"' in vault
    assert '"data/live/omega_target_calibration.json"' in vault
    assert "Update Omega T1 T2 T3 target-learning evidence" in workflow
    assert "python -m scripts.run_omega_target_learning" in workflow
    assert "continue-on-error: true" in workflow
    assert "if: github.event_name != 'push'" in workflow


def test_contract_guardian_runtime_state_has_one_omega_writer() -> None:
    vault = Path("scripts/runtime_state_vault.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert '"data/live/contract_guardian_state.json"' in vault
    assert '"public/data/contract_guardian.json"' in vault
    assert "Track selected contracts with Contract Guardian" in workflow
    assert "python -m scripts.run_contract_guardian" in workflow
