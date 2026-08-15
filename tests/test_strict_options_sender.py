from scripts import send_strict_options_alerts as sender


def _signal():
    return {
        "symbol": "XYZ",
        "direction": "CALL",
        "direction_label": "CALL",
        "signal_grade": "A+",
        "strict_score": 92,
        "side_consensus_score": 91,
        "flow_momentum_score": 88,
        "free_alert_eligible": True,
        "contract_symbol": "XYZ260918C00100000",
        "option_type": "call",
        "expiration": "2026-09-18",
        "strike": 100,
        "dte": 34,
        "bid": 4.9,
        "ask": 5.1,
        "spread_pct": 0.04,
        "delta": 0.52,
        "gamma": 0.035,
        "iv": 0.34,
        "volume": 1800,
        "open_interest": 3200,
        "vol_to_oi_ratio": 1.8,
        "reward_risk_1": 1.5,
        "gamma_context": "CALL_HEAVY_PROXY",
        "gamma_context_alignment": 0.25,
        "gamma_coverage_pct": 90,
        "oi_coverage_pct": 95,
        "call_wall": 105,
        "put_wall": 95,
        "strict_reasons": ["contract score 94/100", "flow momentum 88/100"],
        "occ_side_context": {"available": True, "call_volume": 15000, "put_volume": 10000, "dominance_ratio": 1.5},
    }


def test_free_mode_can_send_only_separately_qualified_signal(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", sent.append)
    monkeypatch.setenv("OPTIONS_FREE_ALERTS_ENABLED", "true")
    monkeypatch.setenv("OPTIONS_FREE_ALERT_MIN_SCORE", "87")
    payload = {
        "path": "options",
        "provider_readiness": {"production_quote_ready": False, "status": "RESEARCH_ONLY"},
        "free_directional_signals": [_signal()],
    }
    state = {"sent": {}}
    count = sender.send(payload, state)
    assert count == 1
    assert state["mode"] == "free"
    assert "بيانات مجانية" in sent[0]
    assert "CALL A+" in sent[0]

    count_again = sender.send(payload, state)
    assert count_again == 0


def test_free_mode_rejects_non_a_signal(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", sent.append)
    row = _signal()
    row["signal_grade"] = "B+"
    payload = {
        "path": "options",
        "provider_readiness": {"production_quote_ready": False, "status": "RESEARCH_ONLY"},
        "free_directional_signals": [row],
    }
    assert sender.send(payload, {"sent": {}}) == 0
    assert sent == []


def test_disabled_free_mode_stays_blocked(monkeypatch):
    monkeypatch.setenv("OPTIONS_FREE_ALERTS_ENABLED", "false")
    payload = {
        "path": "options",
        "provider_readiness": {"production_quote_ready": False, "status": "RESEARCH_ONLY"},
        "free_directional_signals": [_signal()],
    }
    state = {"sent": {}}
    assert sender.send(payload, state) == 0
    assert state["mode"] == "blocked"
