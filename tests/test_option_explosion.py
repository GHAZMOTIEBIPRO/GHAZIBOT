from options_radar.option_explosion import score_option_explosion


def test_option_explosion_rewards_repeated_accelerating_liquid_contract():
    strong = score_option_explosion({"volume":2400,"open_interest":900,"vol_to_oi_ratio":2.6,"spread_pct":0.04,"flow_momentum_score":90,"repeat_flow_hits":4,"flow_notional_velocity_per_min":50000,"gamma":0.08,"delta":0.47,"iv":0.65,"dte":7,"strict_score":94,"side_consensus_score":92,"strike_cluster_score":85})
    weak = score_option_explosion({"volume":20,"open_interest":40,"vol_to_oi_ratio":0.3,"spread_pct":0.22,"flow_momentum_score":35,"repeat_flow_hits":0,"gamma":0.01,"delta":0.1,"iv":0.5,"dte":7,"strict_score":55,"side_consensus_score":50})
    assert strong["score"] > weak["score"]
    assert strong["label"] in {"HIGH","BUILDING"}
    assert "wide_spread_for_profile" in weak["blockers"]


def test_option_explosion_assigns_horizon_from_dte():
    assert score_option_explosion({"dte":1})["horizon"] == "INTRADAY_0_2D"
    assert score_option_explosion({"dte":7})["horizon"] == "WEEK_3_10D"
    assert score_option_explosion({"dte":30})["horizon"] == "SWING_2_6W"


def test_option_explosion_uses_dynamic_profiles():
    premium = score_option_explosion({"dte": 7, "delta": 0.45, "gamma": 0.08, "volume": 1000, "open_interest": 500, "vol_to_oi_ratio": 2.0, "spread_pct": 0.08})
    swing = score_option_explosion({"dte": 30, "delta": 0.45, "gamma": 0.03, "theta": -0.02, "volume": 1000, "open_interest": 1500, "vol_to_oi_ratio": 1.2, "spread_pct": 0.08})
    event = score_option_explosion({"dte": 14, "event_trade": True, "iv_percentile": 0.75, "iv_acceleration_pct": 8, "delta": 0.45, "gamma": 0.04, "volume": 1000, "open_interest": 1200, "vol_to_oi_ratio": 1.4, "spread_pct": 0.08})
    assert premium["profile"] == "PREMIUM_EXPLOSION"
    assert swing["profile"] == "SWING"
    assert event["profile"] == "EVENT"
    assert event["weights"]["surface"] > swing["weights"]["surface"]
    assert "volatility_surface" in event["components"]


def test_high_event_iv_without_verified_prints_gets_crush_penalty():
    row = {
        "dte": 14,
        "event_trade": True,
        "iv": 1.7,
        "iv_percentile": 0.95,
        "delta": 0.45,
        "gamma": 0.04,
        "volume": 1000,
        "open_interest": 1000,
        "vol_to_oi_ratio": 1.5,
        "spread_pct": 0.08,
    }
    result = score_option_explosion(row)
    assert result["penalties"]["iv_crush"] > 0
