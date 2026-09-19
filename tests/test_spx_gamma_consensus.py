from options_radar.spx_gamma_consensus import build_spx_gamma_consensus


def test_consensus_agreement():
    result = build_spx_gamma_consensus({
        "daily_gamma": {"available": True, "net_gex_dollars": 10},
        "intraday_0dte": {"available": True, "net_0dte_gex": 20},
    })
    assert result["verdict"] == "POSITIVE_GAMMA"
    assert result["agreement_ratio"] == 1.0
    assert result["affects_signal_score"] is False


def test_consensus_conflict():
    result = build_spx_gamma_consensus({
        "daily_gamma": {"available": True, "net_gex_dollars": 10},
        "intraday_0dte": {"available": True, "net_0dte_gex": -20},
    })
    assert result["verdict"] == "CONFLICT"
    assert result["agreement_ratio"] == 0.5
