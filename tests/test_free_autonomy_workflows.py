from __future__ import annotations

from pathlib import Path


def _workflow(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_health_watches_actual_stock_and_options_radar():
    text = _workflow("radar-health.yml")
    assert "stock-radar.yml" in text
    assert "options-contract-radar.yml" in text
    assert "options-research-enrichment.yml" not in text
    assert "independent-options-radar" in text


def test_health_is_transition_based_and_market_gated():
    text = _workflow("radar-health.yml")
    assert "market_clock_gate.py --mode regular" in text
    assert "send_radar_health.py" in text
    assert "Radar health is quiet because XNYS regular session is closed" in text
    assert 'cron: "*/15 ' not in text
    assert 'cron: "11,26,41,56 13-22 * * 1-5"' in text


def test_health_does_not_hide_failed_latest_run_behind_old_success():
    text = _workflow("radar-health.yml")
    assert "--status completed --branch main --limit 1" in text
    assert 'latest_conclusion' in text
    assert '"status": "CRITICAL"' in text
    assert "آخر تشغيل لمسار" in text


def test_health_detects_stale_payloads_without_user_intervention():
    text = _workflow("radar-health.yml")
    assert "guard('.health/stocks/stocks_latest.json', 45.0)" in text
    assert "guard('.health/options/options_latest.json', 45.0)" in text
    assert "انقطاع التحديث تلقائيًا" in text


def test_health_state_is_preserved_even_if_notification_step_fails():
    text = _workflow("radar-health.yml")
    assert "if: always() && steps.market.outputs.open == 'true'" in text
