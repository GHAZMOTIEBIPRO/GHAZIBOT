from options_radar.target_horizon import estimate_target_horizon


def test_target_horizon_maps_atr_distance_to_time_bucket():
    stock = {"symbol":"NVDA","price":100,"atr":4,"setup_side":"call","technical_direction":"bullish","relative_volume":2.2}
    target_map = {"t1":{"price":104},"t2":{"price":108},"t3":{"price":116}}
    result = estimate_target_horizon(stock, target_map)
    assert result["targets"][0]["horizon_bucket"] == "INTRADAY_1D"
    assert result["targets"][1]["horizon_bucket"] == "SHORT_1_3D"
    assert result["targets"][2]["horizon_bucket"] == "POSITION_1_4W"
    assert result["timeframe_alignment"] == "ALIGNED"


def test_target_horizon_does_not_claim_probability_or_guarantee():
    result = estimate_target_horizon({"price":100,"atr":5}, {"t1":{"price":105}})
    assert result["is_probability"] is False
    assert result["is_guarantee"] is False
