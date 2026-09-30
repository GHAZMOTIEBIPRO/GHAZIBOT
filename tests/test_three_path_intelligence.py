from options_radar.three_path_intelligence import build_three_paths

def test_three_paths_are_independent():
    result=build_three_paths(
        explosion={"candidates":[{"symbol":"ABCD","price":4.2,"stage":"PRE_EXPLOSION","earlyness":90,"anomaly":80,"acceleration":75,"catalyst_score":90,"score":80}]},
        latest={"stocks":[{"symbol":"NVDA","market_cap":3e12,"score":85,"direction":"BULLISH"}]},
        options={"contracts":[
            {"symbol":"NVDA","contract":"NVDA251017C00150000","dte":17,"volume":5000,"open_interest":1000,"score":90,"direction":"CALL"},
            {"symbol":"XYZ","contract":"XYZ251003C00005000","dte":3,"volume":9000,"open_interest":500,"score":85,"direction":"CALL"}]},
    )
    assert result["small_cap_pre_explosion"][0]["symbol"]=="ABCD"
    assert result["large_cap_contract_selection"][0]["symbol"]=="NVDA"
    assert result["contract_first_radar"][0]["symbol"] in {"NVDA","XYZ"}

def test_small_cap_excludes_over_ten():
    result=build_three_paths(explosion={"candidates":[{"symbol":"ABCD","price":10.01,"earlyness":100,"anomaly":100,"acceleration":100,"catalyst_score":100,"score":100}]},latest={},options={})
    assert result["small_cap_pre_explosion"]==[]

def test_small_cap_gets_same_cycle_option_bridge():
    result=build_three_paths(
        explosion={"candidates":[{"symbol":"ABCD","price":4.2,"stage":"PRESSURE_BUILDING","earlyness":90,"anomaly":80,"acceleration":75,"catalyst_score":90,"score":80}]},
        latest={},
        options={"contracts":[{"symbol":"ABCD","contract":"ABCD261016C00005000","dte":16,"volume":4000,"open_interest":1000,"score":88,"direction":"CALL","delta":0.55,"gamma":0.08,"source":"test"}]},
    )
    bridge=result["small_cap_pre_explosion"][0]["option_bridge"]
    assert bridge["available"] is True
    assert bridge["contract"]=="ABCD261016C00005000"
    assert bridge["volume_oi"]==4.0
