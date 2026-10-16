from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


def _workflow(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_stock_radar_delivers_telegram_in_same_workflow_after_core_state_persistence():
    text = _workflow("stock-radar.yml")
    send_label = "Send qualified stock alert directly after persisted validation"
    persist_label = "Upload stock learning state"
    assert send_label in text
    assert "python -m scripts.send_independent_path_alerts" in text
    assert "name: stock-telegram-state" in text
    assert "if: always() && steps.market_day.outputs.open == 'true' && env.TELEGRAM_READY == 'true'" in text
    assert text.index(persist_label) < text.index(send_label)


def test_options_radar_delivers_telegram_in_same_workflow_after_core_state_persistence():
    text = _workflow("options-contract-radar.yml")
    send_label = "Send strict option alert directly after persisted validation"
    persist_label = "Upload independent options state"
    assert send_label in text
    assert "python -m scripts.send_strict_options_alerts" in text
    assert "name: options-telegram-state" in text
    assert "if: always() && steps.market.outputs.open == 'true' && env.TELEGRAM_READY == 'true'" in text
    assert text.index(persist_label) < text.index(send_label)


def test_old_stock_and_options_telegram_workflows_are_manual_only():
    stock = _workflow("stock-telegram-alerts.yml")
    options = _workflow("options-telegram-alerts.yml")
    for text in (stock, options):
        assert "workflow_dispatch:" in text
        assert "workflow_run:" not in text
        assert "Manual Fallback" in text


def test_cross_confirmation_reads_direct_radar_registries():
    text = _workflow("cross-confirmation.yml")
    assert '"BLACK BOX Omega Stock Radar"' in text
    assert '"BLACK BOX Omega Options Contract Radar"' in text
    assert '"BLACK BOX Omega Options Research Enrichment"' not in text
    assert "for workflow in stock-radar.yml stock-telegram-alerts.yml" in text
    assert "for workflow in options-contract-radar.yml options-telegram-alerts.yml" in text


def test_direct_delivery_keeps_stock_and_options_independence_guards():
    stock = _workflow("stock-radar.yml")
    options = _workflow("options-contract-radar.yml")
    assert "assert payload['independent_from_options_radar'] is True" in stock
    assert "assert payload['policy']['options_flow_required'] is False" in stock
    assert "assert payload['independent_from_stock_radar'] is True" in options
    assert "one_side_one_contract_per_symbol_strict_consensus" in options


def test_direct_delivery_restores_old_state_during_migration():
    stock = _workflow("stock-radar.yml")
    options = _workflow("options-contract-radar.yml")
    assert "for workflow in stock-radar.yml stock-telegram-alerts.yml" in stock
    assert "for workflow in options-contract-radar.yml options-telegram-alerts.yml" in options


def test_delivery_state_accepts_completed_runs_but_core_state_remains_success_only():
    stock = _workflow("stock-radar.yml")
    options = _workflow("options-contract-radar.yml")

    # Telegram delivery state is idempotency evidence. A failed run may still
    # contain valid state for messages delivered before a later send failed.
    assert 'gh run list --workflow "$workflow" --status completed --branch main' in stock
    assert 'gh run list --workflow "$workflow" --status completed --branch main' in options

    # Core learning/market state must remain stricter and only restore from
    # successful runs, so Telegram reliability can never weaken analysis state.
    assert "gh run list --workflow stock-radar.yml --status success --branch main" in stock
    assert "gh run list --workflow options-contract-radar.yml --status success --branch main" in options


def test_fast_radar_explicitly_dispatches_stock_validation_for_same_run():
    fast = _workflow("fast-explosion-radar.yml")
    stock = _workflow("stock-radar.yml")
    assert "actions: write" in fast
    assert 'gh workflow run stock-radar.yml' in fast
    assert '-f source_run_id="$GITHUB_RUN_ID"' in fast
    assert fast.index("name: fast-market-state") < fast.index("Dispatch dependent stock validation")
    assert "workflow_run:" not in stock
    assert "\n  push:\n" in stock
    assert '.github/workflows/stock-radar.yml' in stock
    assert "verify-workflow-registration:" in stock
    assert "if: github.event_name == 'push'" in stock
    assert "if: github.event_name == 'workflow_dispatch'" in stock
    assert "No stock scan, Telegram sends, or secret access permitted in this job." in stock
    assert stock.index("verify-workflow-registration:") < stock.index("deep-stock-validation:")
    assert "source_run_id:" in stock
    assert 'current="${{ inputs.source_run_id }}"' in stock
    assert '"BLACK BOX Omega Fast Explosion Radar"' in stock
    assert '"$source_branch" != "main"' in stock
    assert '"$status" != "completed" || "$conclusion" != "success"' in stock
    assert 'gh run download "$current" -n fast-market-state' in stock
    assert "Exact successful Fast Radar artifact is missing" in stock
    assert 'source_name="$(printf' in stock
    assert 'source_branch="$(printf' in stock
    assert 'Stock Radar source verified' in stock
    assert "Stock Telegram not ready" in stock


def test_stock_registration_smoke_is_isolated_from_real_alert_job():
    """A deployment smoke must never send a Telegram message to a user."""
    raw = _workflow("stock-radar.yml")
    parsed = yaml.safe_load(raw)
    jobs = parsed["jobs"]
    verify = jobs["verify-workflow-registration"]
    deep = jobs["deep-stock-validation"]
    assert verify["if"] == "github.event_name == 'push'"
    assert deep["if"] == "github.event_name == 'workflow_dispatch'"
    assert verify["permissions"] == {"contents": "read"}
    assert not any("TELEGRAM" in str(step.get("env", "")) for step in verify["steps"])
    assert not any("telegram_transport" in str(step.get("run", "")) for step in verify["steps"])


def test_stock_radar_workflow_yaml_parses_and_embedded_bash_compiles():
    """Prevent the exact zero-job GitHub invalid-workflow regression."""
    raw = _workflow("stock-radar.yml")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict)
    assert "deep-stock-validation" in parsed["jobs"]
    steps = parsed["jobs"]["deep-stock-validation"]["steps"]
    item = next(step for step in steps if step.get("name") == "Restore fresh stock discovery payload")
    shell = item["run"]
    assert "source_name" in shell and "source_branch" in shell
    assert "Stock Radar source verified" in shell
    assert "if [[ -n" in shell
    assert "fi" in shell
    if shutil.which("bash") is None:
        pytest.skip("Bash unavailable in this environment")
    check = subprocess.run(["bash", "-n"], input=shell, text=True, capture_output=True, check=False)
    assert check.returncode == 0, check.stderr
