from pathlib import Path


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
