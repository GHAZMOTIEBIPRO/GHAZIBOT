from options_radar.radar_health import assess_options_health, assess_stock_health


def test_stock_health_critical_when_deep_stage_disappears():
    payload = {
        "summary": {"fast_actionable": 10, "stocks_deep_validated": 0, "official_causes": 0},
        "errors": [],
    }
    health = assess_stock_health(payload)
    assert health["status"] == "CRITICAL"


def test_options_zero_selected_is_not_automatically_failure():
    payload = {
        "summary": {
            "symbols_scanned": 20,
            "contracts_selected": 0,
            "official_optionability_verified": True,
            "provider": "tradier",
        },
        "errors": {},
        "universe": {"attention_sources": ["OCC"]},
        "market_regime_detail": {"data_quality": "complete"},
    }
    health = assess_options_health(payload)
    assert health["status"] == "HEALTHY"


def test_snapshot_provider_is_degraded_not_critical():
    payload = {
        "summary": {
            "symbols_scanned": 20,
            "contracts_selected": 2,
            "official_optionability_verified": True,
            "provider": "yahoo",
        },
        "errors": {},
        "universe": {},
        "market_regime_detail": {"data_quality": "complete"},
    }
    health = assess_options_health(payload)
    assert health["status"] == "DEGRADED"
