from datetime import datetime, timezone

from options_radar.v11_gate import evaluate_v11_signal


def _row(**overrides):
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "strict_score": 94,
        "flow_momentum_score": 82,
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
        "quote_timestamp": now,
    }
    base.update(overrides)
    return base


def test_v11_approves_only_full_quorum():
    decision = evaluate_v11_signal(_row())
    assert decision["approved"] is True
    assert decision["state"] == "CONFIRMED"
    assert decision["telegram_eligible"] is True


def test_v11_rejects_single_source_even_when_model_score_is_high():
    decision = evaluate_v11_signal(_row(fabric_independent_source_count=1))
    assert decision["approved"] is False
    assert "v11_independent_source_quorum_not_met" in decision["blockers"]


def test_v11_rejects_cross_provider_quote_conflict():
    decision = evaluate_v11_signal(
        _row(fabric_consensus_pass=False, fabric_quote_divergence_pct=0.18)
    )
    assert decision["approved"] is False
    assert "v11_cross_provider_quote_conflict" in decision["blockers"]


def test_v11_rejects_delayed_research_quote():
    decision = evaluate_v11_signal(
        _row(source="yahoo research", freshness_label="delayed")
    )
    assert decision["approved"] is False
    assert "v11_execution_quote_not_ready" in decision["blockers"]
