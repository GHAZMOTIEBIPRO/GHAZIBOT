from options_radar.omega_decision import apply_omega_gate, evaluate_contract


def _row(**overrides):
    row = {
        "strict_score": 92,
        "flow_momentum_score": 78,
        "data_quality": 0.95,
        "gamma_context_alignment": 0.30,
        "gamma_coverage_pct": 80,
        "oi_coverage_pct": 80,
        "occ_side_context": {"aligned": True, "opposed": False},
        "strict_blockers": [],
    }
    row.update(overrides)
    return row


def test_omega_confirms_convergent_signal():
    decision = evaluate_contract(_row())
    assert decision["state"] == "CONFIRMED"
    assert decision["approved"] is True
    assert decision["quorum"] >= 2


def test_omega_rejects_conflicting_evidence():
    decision = evaluate_contract(
        _row(
            gamma_context_alignment=-0.30,
            occ_side_context={"aligned": True, "opposed": False},
        )
    )
    assert decision["state"] == "NO_TRADE"
    assert decision["approved"] is False
    assert "omega_evidence_conflict" in decision["blockers"]


def test_gate_preserves_research_signal_but_vetoes_free_alert():
    signals = apply_omega_gate(
        [_row(gamma_context_alignment=0.0, occ_side_context={"aligned": False, "opposed": False})]
    )
    assert len(signals) == 1
    assert signals[0]["omega_decision"]["state"] == "NO_TRADE"
    assert signals[0]["free_alert_eligible"] is False
