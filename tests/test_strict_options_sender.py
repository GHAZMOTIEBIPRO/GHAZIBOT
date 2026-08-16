from datetime import datetime, timedelta, timezone

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


def _payload(row=None):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "path": "options",
        "provider_readiness": {"production_quote_ready": False, "status": "RESEARCH_ONLY"},
        "free_directional_signals": [row or _signal()],
    }


def test_free_mode_sends_one_compact_qualified_card(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    monkeypatch.setenv("OPTIONS_FREE_ALERTS_ENABLED", "true")
    monkeypatch.setenv("OPTIONS_FREE_ALERT_MIN_SCORE", "87")
    payload = _payload()
    state = {"sent": {}}
    count = sender.send(payload, state)
    assert count == 1
    assert state["mode"] == "free"
    assert "مجاني/صارم" in sent[0]
    assert "CALL A+" in sent[0]
    assert "100C" in sent[0]
    assert "B/A" in sent[0]
    assert "GEX" in sent[0]
    assert len(sent[0]) < 1200

    record = state["sent"]["XYZ:CALL"]
    assert isinstance(record, dict)
    assert record["symbol"] == "XYZ"
    assert record["direction"] == "CALL"
    assert record["contract_symbol"] == "XYZ260918C00100000"
    assert record["text"] == sent[0]
    assert state["state_schema"] == "telegram_message_registry_v1"

    count_again = sender.send(payload, state)
    assert count_again == 0


def test_sender_records_real_telegram_message_id(monkeypatch):
    class Result:
        message_id = 987

    monkeypatch.setattr(sender, "_send", lambda text: Result())
    state = {"sent": {}}
    assert sender.send(_payload(), state) == 1
    assert state["sent"]["XYZ:CALL"]["message_id"] == 987


def test_old_string_state_remains_backward_compatible(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    state = {"sent": {"XYZ:CALL": "old-fingerprint"}}
    assert sender.send(_payload(), state) == 1
    assert len(sent) == 1
    assert isinstance(state["sent"]["XYZ:CALL"], dict)


def test_free_mode_rejects_non_a_signal(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    row = _signal()
    row["signal_grade"] = "B+"
    assert sender.send(_payload(row), {"sent": {}}) == 0
    assert sent == []


def test_disabled_free_mode_stays_blocked(monkeypatch):
    monkeypatch.setenv("OPTIONS_FREE_ALERTS_ENABLED", "false")
    state = {"sent": {}}
    assert sender.send(_payload(), state) == 0
    assert state["mode"] == "blocked"


def test_stale_payload_is_blocked_before_any_send(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    monkeypatch.setenv("OPTIONS_PAYLOAD_MAX_AGE_MINUTES", "45")
    payload = _payload()
    payload["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state = {"sent": {}}
    assert sender.send(payload, state) == 0
    assert state["mode"] == "stale_blocked"
    assert state["blocked_reason"] == "MISSING_OR_STALE_OPTIONS_PAYLOAD"
    assert sent == []


def test_missing_payload_timestamp_is_blocked(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    payload = _payload()
    payload.pop("generated_at")
    state = {"sent": {}}
    assert sender.send(payload, state) == 0
    assert state["mode"] == "stale_blocked"
    assert sent == []
