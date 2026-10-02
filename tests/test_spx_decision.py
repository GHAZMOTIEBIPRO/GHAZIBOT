from options_radar.spx_decision import build_spx_trade_map


def _base(**overrides):
    payload = {
        "spot": 6700.0,
        "vwap": 6698.0,
        "vix": 16.0,
        "zero_gamma_flip": 6702.0,
        "call_wall": 6750.0,
        "put_wall": 6650.0,
        "opening_range_high": 6708.0,
        "opening_range_low": 6688.0,
        "age_minutes": 2.0,
        "gamma_regime": "negative",
    }
    payload.update(overrides)
    return payload


def test_spx_map_has_call_put_and_no_trade_boundaries():
    result = build_spx_trade_map(_base())
    assert result["call_above"] > result["put_below"]
    assert result["no_trade_zone"]["high"] == result["call_above"]
    assert result["no_trade_zone"]["low"] == result["put_below"]
    assert result["call_target"] > result["call_above"]
    assert result["put_target"] < result["put_below"]
    assert result["gamma_is_verified_dealer_inventory"] is False


def test_spx_inside_zone_is_no_trade():
    initial = build_spx_trade_map(_base())
    mid = (initial["call_above"] + initial["put_below"]) / 2.0
    result = build_spx_trade_map(_base(spot=mid))
    assert result["state"] == "NO_TRADE"


def test_spx_above_call_trigger_is_call():
    initial = build_spx_trade_map(_base())
    result = build_spx_trade_map(_base(spot=initial["call_above"] + 10))
    assert result["state"] == "CALL"


def test_spx_below_put_trigger_is_put():
    initial = build_spx_trade_map(_base())
    result = build_spx_trade_map(_base(spot=initial["put_below"] - 10))
    assert result["state"] == "PUT"


def test_spx_stale_data_fails_closed():
    result = build_spx_trade_map(_base(age_minutes=45))
    assert result["state"] == "DATA_INSUFFICIENT"
    assert result["call_above"] is None
