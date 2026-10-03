from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from options_radar.data_fabric_runtime import _execution_quote_audit
from options_radar.outcome_learning import _rows_for_tracking
from scripts.run_options_radar_hardened import _quarantine_research_contracts
from scripts.send_options_intelligence_v7 import _signals


def _v11_row(**overrides):
    row = {
        "symbol": "XYZ",
        "contract_symbol": "XYZ261120C00100000",
        "direction": "CALL",
        "direction_label": "CALL",
        "option_type": "call",
        "signal_grade": "A+",
        "strict_grade": "A+",
        "strict_score": 94,
        "flow_momentum_score": 82,
        "side_consensus_score": 90,
        "data_quality": 0.96,
        "gamma_context_alignment": 0.31,
        "gamma_coverage_pct": 90,
        "oi_coverage_pct": 90,
        "occ_side_context": {"aligned": True, "opposed": False},
        "strict_blockers": [],
        "fabric_independent_source_count": 2,
        "fabric_consensus_pass": True,
        "fabric_quote_divergence_pct": 0.01,
        "source": "polygon_options brokerage feed",
        "freshness_label": "real-time",
        "bid": 2.10,
        "ask": 2.20,
        "quote_timestamp": datetime.now(timezone.utc).isoformat(),
        "free_alert_eligible": True,
    }
    row.update(overrides)
    return row


def test_execution_quote_audit_separates_trade_time_from_fresh_opra_quote():
    now = datetime.now(timezone.utc).isoformat()
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": "TRADE_ONLY",
                "source": "tradier",
                "freshness_label": "Tradier brokerage feed",
                "bid": 1.0,
                "ask": 1.1,
                "updated_at": now,
                "last_trade_timestamp": now,
                "timestamp_kind": "last_trade",
            },
            {
                "contract_symbol": "OPRA_READY",
                "source": "yahoo + alpaca_opra_stream",
                "freshness_label": "Alpaca OPRA stream; execution-grade quote overlay",
                "fabric_quote_provider": "alpaca_opra_stream",
                "stream_feed": "opra",
                "stream_execution_grade": True,
                "bid": 2.0,
                "ask": 2.1,
                "quote_timestamp": now,
                "timestamp_kind": "quote",
            },
        ]
    )

    audit = _execution_quote_audit(frame, max_quote_age_seconds=120)

    assert audit["execution_quote_checked_contracts"] == 2
    assert audit["execution_quote_ready_contracts"] == 1
    assert audit["verifiable_quote_timestamp_contracts"] == 1


def test_hardened_runner_promotes_only_v11_approved_directional_rows():
    approved = _v11_row()
    rejected = _v11_row(
        contract_symbol="XYZ261120C00105000",
        source="yahoo research",
        freshness_label="delayed",
    )
    payload = {
        "contracts": [approved, rejected],
        "top_calls": [approved, rejected],
        "top_puts": [],
        "directional_signals": [approved, rejected],
        "summary": {},
        "flow_policy": {},
    }
    readiness = {
        "status": "LIVE_QUOTES_NO_TRADE_FLOW",
        "production_quote_ready": True,
        "production_flow_ready": False,
    }

    _quarantine_research_contracts(payload, readiness)

    assert len(payload["research_directional_signals"]) == 2
    assert len(payload["production_directional_signals"]) == 1
    assert payload["production_directional_signals"][0]["contract_symbol"] == approved[
        "contract_symbol"
    ]
    assert len(payload["free_directional_signals"]) == 1
    assert len(payload["directional_signals"]) == 1
    assert payload["summary"]["v11_rejected_directional_signals"] == 1
    assert payload["flow_policy"]["production_directional_requires_v11"] is True


def test_intelligence_sender_never_uses_raw_directional_fallback():
    raw = _v11_row(contract_symbol="RAW")
    free = _v11_row(contract_symbol="FREE")
    payload = {
        "provider_readiness": {
            "production_quote_ready": True,
            "status": "LIVE_QUOTES_NO_TRADE_FLOW",
        },
        "directional_signals": [raw],
        "production_directional_signals": [],
        "free_directional_signals": [free],
    }

    selected = _signals(payload)

    assert [row["contract_symbol"] for row in selected] == ["FREE"]


def test_outcome_learning_never_calls_raw_directional_rows_production():
    raw = _v11_row(contract_symbol="RAW")
    free = _v11_row(contract_symbol="FREE")
    payload = {
        "provider_readiness": {
            "production_quote_ready": True,
            "status": "LIVE_QUOTES_NO_TRADE_FLOW",
        },
        "directional_signals": [raw],
        "production_directional_signals": [],
        "free_directional_signals": [free],
    }

    mode, rows, _ = _rows_for_tracking(payload)

    assert mode == "free"
    assert [row["contract_symbol"] for row in rows] == ["FREE"]
