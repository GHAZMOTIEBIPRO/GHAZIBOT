from options_radar.omega_target_map import build_target_map


def test_target_map_preserves_underlying_levels_and_marks_modeled_t3():
    result = build_target_map(
        {
            "symbol": "XYZ",
            "setup_side": "call",
            "price": 100,
            "entry_low": 99,
            "entry_high": 101,
            "invalidation": 96,
            "target_1": 103,
            "target_2": 106,
        }
    )
    assert result["entry"] == {"low": 99.0, "high": 101.0, "source": "stock_setup"}
    assert result["invalidation"]["price"] == 96.0
    assert result["t1"]["price"] == 103.0
    assert result["t2"]["price"] == 106.0
    assert result["t3"]["provenance"] == "MODELED"
    assert "not a price forecast" in result["statement"]


def test_target_map_uses_structural_levels_when_available():
    result = build_target_map(
        {
            "symbol": "PUT",
            "setup_side": "put",
            "price": 50,
            "entry_low": 49.5,
            "entry_high": 50.5,
            "invalidation": 53,
            "pdl": 48,
            "previous_week_low": 45,
            "target_1": 47,
            "target_2": 44,
        }
    )
    assert result["t1"]["price"] == 48.0
    assert result["t1"]["provenance"] == "SOURCE_DERIVED"
    assert result["target_map_quality"] >= 80
