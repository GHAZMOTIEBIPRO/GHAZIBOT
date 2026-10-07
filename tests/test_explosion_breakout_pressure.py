from options_radar.explosion_intelligence import build_delta_signals


def _payload(pressure: float) -> dict:
    return {
        "stocks": [
            {
                "symbol": "COIL",
                "price": 10.0,
                "performance_day": 2.0,
                "performance_week": 6.0,
                "relative_volume": 1.6,
                "volume": 600_000,
                "breakout_pressure_score": pressure,
            }
        ]
    }


def test_breakout_pressure_is_bonus_not_missing_data_penalty():
    plain, _ = build_delta_signals(_payload(0.0))
    coiled, _ = build_delta_signals(_payload(90.0))

    assert len(plain) == 1
    assert len(coiled) == 1
    assert coiled[0].score > plain[0].score
    assert coiled[0].components["breakout_pressure"] == 90.0
    assert any("Breakout pressure" in reason for reason in coiled[0].reasons)
