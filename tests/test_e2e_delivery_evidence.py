from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.write_e2e_delivery_evidence import build_evidence


def test_evidence_links_candidate_provider_v11_and_telegram_without_message_text() -> None:
    row = {
        "signal_id": "sig-real-1",
        "symbol": "SPY",
        "direction": "CALL",
        "contract_symbol": "SPY260101C00500000",
        "expiration": "2026-01-01",
        "strike": 500,
        "dte": 30,
        "bid": 2.1,
        "ask": 2.2,
        "quote_timestamp": "2025-12-01T15:00:00+00:00",
        "volume": 1000,
        "open_interest": 5000,
        "delta": 0.5,
        "iv": 0.2,
        "spread_pct": 0.045,
        "source": "licensed-provider",
        "fabric_independent_source_count": 2,
        "fabric_consensus_pass": True,
        "strict_score": 92,
        "signal_grade": "A+",
        "catalyst": "official filing",
    }
    payload = {
        "path": "options",
        "generated_at": "2025-12-01T15:00:00+00:00",
        "provider_readiness": {
            "status": "LIVE_FLOW_READY",
            "production_quote_ready": True,
            "production_flow_ready": True,
        },
        "production_directional_signals": [row],
    }
    state = {
        "last_sent_count": 1,
        "mode": "production",
        "sent": {
            "SPY:CALL": {
                "message_id": 12345,
                "text": "must not be copied into evidence",
            }
        },
    }

    evidence = build_evidence(
        payload,
        state,
        run_id="9876",
        now=datetime(2025, 12, 1, 15, 1, tzinfo=timezone.utc),
    )
    candidate = evidence["candidates"][0]
    assert evidence["run_id"] == "9876"
    assert candidate["signal_id"] == "sig-real-1"
    assert candidate["provider_validation"]["provider"] == "licensed-provider"
    assert candidate["provider_validation"]["quote_timestamp"] == row["quote_timestamp"]
    assert all(candidate["provider_validation"]["field_presence"].values())
    assert candidate["v11"]["version"] == "OMEGA_V11"
    assert evidence["telegram"]["sent_count"] == 1
    assert evidence["telegram"]["message_ids"] == [12345]
    assert "must not be copied" not in json.dumps(evidence)
    assert evidence["contains_secrets"] is False


def test_evidence_fails_closed_and_records_block_without_telegram_send() -> None:
    evidence = build_evidence(
        {
            "path": "options",
            "generated_at": "2025-12-01T15:00:00+00:00",
            "provider_readiness": {
                "status": "FALLBACK_ONLY",
                "production_quote_ready": False,
                "production_flow_ready": False,
            },
            "free_directional_signals": [
                {"symbol": "SPY", "direction": "CALL", "source": "yahoo/yfinance"}
            ],
        },
        {"last_sent_count": 0, "mode": "free", "blocked_reason": "V11_NO_TRADE", "sent": {}},
        run_id="blocked-run",
        now=datetime(2025, 12, 1, 15, 1, tzinfo=timezone.utc),
    )
    assert evidence["provider_readiness"]["production_quote_ready"] is False
    assert evidence["telegram"]["sent_count"] == 0
    assert evidence["telegram"]["blocked_reason"] == "V11_NO_TRADE"
    assert evidence["candidates"][0]["v11"]["approved"] is False


def test_workflow_uploads_e2e_evidence_separately_from_market_payload() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/options-contract-radar.yml").read_text(encoding="utf-8")
    assert "Record non-sensitive options E2E delivery evidence" in workflow
    assert "name: options-e2e-evidence" in workflow
    assert "data/live/e2e_delivery_evidence.json" in workflow
    assert "options_latest.json" in workflow
