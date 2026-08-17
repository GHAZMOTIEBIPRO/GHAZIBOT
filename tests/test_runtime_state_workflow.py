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
