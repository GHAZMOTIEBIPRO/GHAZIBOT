from options_radar.premium_target_engine import (
    black_scholes_price,
    build_premium_target_scenarios,
)


def test_black_scholes_call_value_rises_with_spot():
    low = black_scholes_price(
        spot=100,
        strike=100,
        years=30 / 365,
        rate=0.04,
        volatility=0.35,
        side="call",
    )
    high = black_scholes_price(
        spot=110,
        strike=100,
        years=30 / 365,
        rate=0.04,
        volatility=0.35,
        side="call",
    )
    assert low is not None
    assert high is not None
    assert high > low


def test_premium_target_engine_returns_t1_t2_t3_ranges():
    contract = {
        "side": "CALL",
        "strike": 100,
        "underlying_price": 100,
        "dte": 30,
        "iv": 0.40,
        "bid": 4.8,
        "ask": 5.0,
        "mid": 4.9,
    }
    stock = {
        "price": 100,
        "target_1": 104,
        "target_2": 108,
        "target_3": 114,
        "invalidation": 96,
    }
    opportunity = {
        "target_map": {
            "t1": {"price": 104},
            "t2": {"price": 108},
            "t3": {"price": 114},
            "invalidation": {"price": 96},
        },
        "target_horizon": {
            "primary_horizon": "SHORT_1_3D",
            "targets": [
                {"target": "T1", "horizon_bucket": "INTRADAY_1D"},
                {"target": "T2", "horizon_bucket": "SHORT_1_3D"},
                {"target": "T3", "horizon_bucket": "SWING_3_7D"},
            ],
        },
    }

    result = build_premium_target_scenarios(contract, stock, opportunity)

    assert result["available"] is True
    assert result["entry_method"] == "ask"
    assert set(result["targets"]) == {"t1", "t2", "t3"}
    assert result["targets"]["t1"]["premium_low"] <= result["targets"]["t1"]["premium_base"]
    assert result["targets"]["t1"]["premium_base"] <= result["targets"]["t1"]["premium_high"]
    assert result["targets"]["t3"]["premium_base"] > result["targets"]["t1"]["premium_base"]
    assert result["invalidation"]["premium_base"] < result["entry_premium_reference"]
    assert result["is_guarantee"] is False
