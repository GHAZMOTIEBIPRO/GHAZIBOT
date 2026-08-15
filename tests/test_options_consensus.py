from options_radar.options_consensus import build_directional_signals, score_contract_strict


def _row(side: str, **overrides):
    row = {
        "symbol": "XYZ",
        "contract_symbol": f"XYZ-{side}",
        "option_type": side,
        "score": 95,
        "flow_momentum_score": 91,
        "data_quality": 0.90,
        "execution_score": 27,
        "reward_risk_1": 1.6,
        "spread_pct": 0.04,
        "vol_to_oi_ratio": 2.8,
        "volume": 1800,
        "open_interest": 3500,
        "delta": 0.50 if side == "call" else -0.50,
        "dte": 28,
        "gamma_concentration_pct": 17,
        "gamma_context_alignment": 0.28 if side == "call" else -0.28,
        "gamma_coverage_pct": 92,
        "oi_coverage_pct": 95,
        "occ_side_context": {
            "available": True,
            "aligned": side == "call",
            "opposed": side == "put",
            "dominance_ratio": 1.35 if side == "call" else 0.74,
            "bonus": 1.05 if side == "call" else -2.0,
        },
    }
    row.update(overrides)
    return row


def test_consensus_emits_only_call_when_put_evidence_opposes():
    signals = build_directional_signals([_row("call"), _row("put")], minimum_score=85, minimum_side_edge=6)
    assert len(signals) == 1
    assert signals[0]["symbol"] == "XYZ"
    assert signals[0]["direction"] == "CALL"
    assert signals[0]["free_alert_eligible"] is True


def test_bad_spread_blocks_otherwise_high_scoring_contract():
    strict, _, blockers = score_contract_strict(_row("call", spread_pct=0.14))
    assert strict < 95
    assert "spread_above_10pct" in blockers
    signals = build_directional_signals([_row("call", spread_pct=0.14)], minimum_score=80)
    assert signals == []


def test_weak_gamma_coverage_is_hard_blocker():
    signals = build_directional_signals(
        [_row("call", gamma_coverage_pct=20, oi_coverage_pct=25)],
        minimum_score=70,
    )
    assert signals == []


def test_ambiguous_call_put_edge_produces_no_signal():
    call = _row("call", gamma_context_alignment=0.10, occ_side_context={"available": False, "bonus": 0})
    put = _row(
        "put",
        gamma_context_alignment=0.10,
        occ_side_context={"available": False, "bonus": 0},
    )
    signals = build_directional_signals([call, put], minimum_score=80, minimum_side_edge=6)
    assert signals == []
