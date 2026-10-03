from pathlib import Path

from options_radar.optionable_universe import IndependentOptionableUniverse
from scripts.build_explosion_options_universe import build_dynamic_options_universe


def test_dynamic_explosion_universe_keeps_early_candidates_and_rejects_extended():
    payload = {
        "generated_at": "2026-10-03T00:00:00Z",
        "candidates": [
            {"symbol": "AAA", "stage": "PRESSURE_BUILDING", "score": 61, "institutional_earlyness": 82},
            {"symbol": "BBB", "stage": "EXTENDED", "score": 99, "institutional_earlyness": 10},
            {"symbol": "CCC", "stage": "IGNITION", "score": 74, "institutional_earlyness": 70},
            {"symbol": "DDD", "stage": "WATCH", "score": 20, "institutional_earlyness": 10, "institutional_anomaly": 20},
        ],
    }
    result = build_dynamic_options_universe(payload, max_symbols=10)
    assert result["symbols"] == ["CCC", "AAA"]
    assert "BBB" not in result["symbols"]
    assert "DDD" not in result["symbols"]
    assert result["discovery_seed_only"] is True
    assert result["options_result_cannot_promote_stock_signal"] is True


def test_dynamic_universe_fingerprint_is_stable_for_same_ranked_symbols():
    payload = {"candidates": [{"symbol": "AAA", "stage": "IGNITION", "score": 80}]}
    first = build_dynamic_options_universe(payload)
    second = build_dynamic_options_universe(payload)
    assert first["fingerprint"] == second["fingerprint"]


class _SeedUniverse(IndependentOptionableUniverse):
    def fetch_official(self):
        rows = [{"underlying_symbol": symbol} for symbol in ("AAPL", "NVDA", "SPY")]
        return ["AAPL", "NVDA", "SPY"], rows, ["EU"], {}, False

    def fetch_cboe_attention(self, limit=100):
        return ["NVDA"], [{"symbol": "NVDA"}], None


def test_configured_priority_leads_same_cycle_universe_but_still_requires_occ():
    result = _SeedUniverse().build(["AAPL", "NOOPTION"], max_symbols=10, configured_priority=True)
    assert result.symbols[:3] == ["AAPL", "NVDA", "SPY"]
    assert "NOOPTION" not in result.symbols
    assert result.official_verified is True
    assert "configured discovery seeds" in result.source


def test_crosscheck_workflow_is_free_only_isolated_and_v11_sender_only():
    text = Path(".github/workflows/explosion-options-crosscheck.yml").read_text(encoding="utf-8")
    assert 'PAID_MARKET_DATA_ALLOWED: "false"' in text
    assert 'FREE_AUTONOMY_MODE: "true"' in text
    assert "workflow_run:" in text
    assert "BLACK BOX Omega Fast Explosion Radar" in text
    assert "--configured-priority" in text
    assert "explosion_options_alert_state.json" in text
    assert "explosion_options_outcomes.json" in text
    assert "send_strict_options_alerts" in text
    assert 'OPTIONS_ALERT_MAX: "0"' in text
    assert "automatic_execution" not in text.lower()
    # A colon-space inside an unquoted YAML plain scalar made this workflow
    # invalid from its first release and GitHub failed before creating a job.
    assert 'run: echo "Explosion options cross-check skipped:' not in text
    assert 'run: |\n          echo "Explosion options cross-check skipped:' in text
