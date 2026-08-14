from scripts.run_options_radar_hardened import _quarantine_research_contracts


def test_fallback_contracts_are_quarantined_from_production():
    payload = {
        "contracts": [{"contract_symbol": "AAA1"}, {"contract_symbol": "AAA2"}],
        "top_calls": [{"contract_symbol": "AAA1"}],
        "top_puts": [{"contract_symbol": "AAA2"}],
        "summary": {"contracts_selected": 2, "calls_selected": 1, "puts_selected": 1},
        "flow_policy": {},
    }
    readiness = {
        "status": "FALLBACK_ONLY",
        "production_quote_ready": False,
        "production_flow_ready": False,
    }

    _quarantine_research_contracts(payload, readiness)

    assert payload["contracts"] == []
    assert payload["top_calls"] == []
    assert payload["top_puts"] == []
    assert len(payload["research_contracts"]) == 2
    assert payload["summary"]["production_alerts_blocked"] is True
    assert payload["summary"]["research_contracts_selected"] == 2
    assert payload["flow_policy"]["fallback_contracts_can_enter_production_alerts"] is False
    assert payload["flow_policy"]["fallback_contracts_can_enter_cross_confirmation"] is False


def test_live_quote_contracts_remain_available_for_production():
    payload = {
        "contracts": [{"contract_symbol": "AAA1"}],
        "top_calls": [{"contract_symbol": "AAA1"}],
        "top_puts": [],
        "summary": {"contracts_selected": 1, "calls_selected": 1, "puts_selected": 0},
    }
    readiness = {
        "status": "LIVE_QUOTES_NO_TRADE_FLOW",
        "production_quote_ready": True,
        "production_flow_ready": False,
    }

    _quarantine_research_contracts(payload, readiness)

    assert len(payload["contracts"]) == 1
    assert payload["summary"]["production_alerts_blocked"] is False
    assert "research_contracts" not in payload
