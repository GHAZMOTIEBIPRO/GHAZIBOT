from options_radar.omega_observability import build_data_status, build_health


def test_stale_option_is_visible_in_data_status():
    payload = {
        "generated_at": "2026-08-07T00:00:00+00:00",
        "options": [{"data_status": "STALE", "last_trade_age_minutes": 90}],
        "stocks": [{"symbol": "XYZ"}],
        "catalysts": [],
        "errors": {},
        "omega": {"validation": {"edge_status": "EDGE NOT YET PROVEN"}},
    }
    status = build_data_status(payload)
    assert status["quality_counts"]["stale_options"] == 1
    assert status["status"] in {"degraded", "stale"}
    assert build_health(payload)["research_status"] == "EDGE NOT YET PROVEN"
