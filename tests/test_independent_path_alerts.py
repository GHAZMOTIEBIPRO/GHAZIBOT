from __future__ import annotations

import scripts.send_independent_path_alerts as sender


def test_option_message_is_compact_and_never_claims_sweep_or_opening_from_snapshot():
    row = {
        "symbol": "NVDA",
        "option_type": "call",
        "expiration": "2026-08-28",
        "dte": 15,
        "strike": 200,
        "bid": 2.1,
        "ask": 2.2,
        "volume": 3000,
        "open_interest": 500,
        "vol_to_oi_ratio": 6.0,
        "delta": 0.45,
        "gamma": 0.02,
        "theta": -0.08,
        "iv": 0.55,
        "spread_pct": 0.045,
        "score": 82,
        "flow_momentum_score": 88,
        "rationale_ar": ["عقد مستقل"],
        "flow_evidence": {
            "execution_pressure_note_ar": "ضغط شراء تقديري وليس إثباتًا",
            "volume_vs_prior_oi_note_ar": "نشاط غير طبيعي فقط",
        },
        "_provider_readiness": {
            "status": "LIVE_QUOTES_NO_TRADE_FLOW",
            "production_quote_ready": True,
            "production_flow_ready": False,
        },
    }
    message = sender._option_message(row)
    assert "NVDA CALL ↑" in message
    assert "200C" in message
    assert "B/A" in message
    assert "السويب/فتح مركز جديد غير مؤكد" in message
    assert "مسار الأوبشن مستقل" in message
    assert len(message) < 1000


def test_stock_message_is_compact_actionable_and_options_are_not_required():
    row = {
        "symbol": "ABC",
        "price": 4.2,
        "move_pct": 7.5,
        "stage": "IGNITION",
        "score": 78,
        "cause": {"status_ar": "السبب الأساسي غير مثبت حتى الآن"},
        "amplifiers": ["حجم مرتفع"],
        "market_status_evidence": [],
    }
    message = sender._stock_message(row)
    assert "Ω | ABC" in message
    assert "بداية انطلاقة" in message
    assert "$4.20" in message
    assert "السبب:" in message
    assert "مسار الأسهم مستقل" in message
    assert len(message) < 1800


def test_options_sender_deduplicates_and_records_message_registry(monkeypatch):
    sent: list[str] = []

    class Result:
        message_id = 1234

    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text) or Result())
    monkeypatch.setenv("OPTIONS_ALERT_MIN_SCORE", "65")
    payload = {
        "path": "options",
        "provider_readiness": {
            "status": "LIVE_QUOTES_NO_TRADE_FLOW",
            "production_quote_ready": True,
            "production_flow_ready": False,
        },
        "contracts": [
            {
                "symbol": "NVDA",
                "contract_symbol": "NVDA260828C00200000",
                "option_type": "call",
                "expiration": "2026-08-28",
                "dte": 15,
                "strike": 200,
                "bid": 2.1,
                "ask": 2.2,
                "volume": 3000,
                "open_interest": 500,
                "vol_to_oi_ratio": 6.0,
                "delta": 0.45,
                "gamma": 0.02,
                "theta": -0.08,
                "iv": 0.55,
                "spread_pct": 0.045,
                "score": 82,
                "flow_momentum_score": 88,
                "flow_rank_score": 86,
            }
        ],
    }
    state = {"sent": {}}
    assert sender.send_options(payload, state) == 1
    assert sender.send_options(payload, state) == 0
    assert len(sent) == 1
    record = state["sent"]["NVDA260828C00200000"]
    assert record["message_id"] == 1234
    assert record["symbol"] == "NVDA"
    assert state["state_schema"] == "telegram_message_registry_v1"


def test_options_sender_fails_closed_on_fallback_data(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    payload = {
        "path": "options",
        "provider_readiness": {
            "status": "FALLBACK_ONLY",
            "production_quote_ready": False,
            "production_flow_ready": False,
        },
        "contracts": [
            {
                "symbol": "NVDA",
                "contract_symbol": "NVDA260828C00200000",
                "option_type": "call",
                "score": 99,
                "flow_momentum_score": 99,
            }
        ],
    }
    state = {"sent": {}}
    assert sender.send_options(payload, state) == 0
    assert sent == []
    assert state["blocked_reason"] == "FALLBACK_ONLY"


def test_stock_sender_does_not_read_options_fields_and_records_message_id(monkeypatch):
    sent: list[str] = []

    class Result:
        message_id = 55

    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text) or Result())
    monkeypatch.setenv("STOCK_ALERT_MIN_SCORE", "72")
    payload = {
        "path": "stocks",
        "stocks": [
            {
                "symbol": "XYZ",
                "price": 5,
                "move_pct": 8,
                "stage": "IGNITION",
                "score": 80,
                "cause": {"status": "NO_PRIMARY_CAUSE_PROVEN", "status_ar": "غير مثبت"},
                "amplifiers": ["سيولة"],
            }
        ],
    }
    state = {"sent": {}}
    assert sender.send_stocks(payload, state) == 1
    assert len(sent) == 1
    assert state["sent"]["XYZ"]["message_id"] == 55
    assert state["sent"]["XYZ"]["kind"] == "stocks"


def test_old_string_fingerprint_state_migrates_cleanly(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text))
    monkeypatch.setenv("STOCK_ALERT_MIN_SCORE", "72")
    payload = {
        "path": "stocks",
        "stocks": [
            {
                "symbol": "XYZ",
                "price": 5,
                "move_pct": 8,
                "stage": "IGNITION",
                "score": 80,
                "cause": {"status": "NEW", "status_ar": "خبر جديد"},
            }
        ],
    }
    state = {"sent": {"XYZ": "legacy-fingerprint"}}
    assert sender.send_stocks(payload, state) == 1
    assert isinstance(state["sent"]["XYZ"], dict)


def test_stock_message_surfaces_explosion_cause_and_research_risk_flag():
    row = {
        "symbol": "MICR",
        "price": 0.18,
        "move_pct": 6.5,
        "stage": "PRESSURE_BUILDING",
        "alert_stage": "WATCH",
        "score": 68,
        "cause": {"status_ar": "السبب الأساسي غير مثبت حتى الآن"},
        "explosion_cause": {
            "primary": "SUPPLY_VACUUM",
            "primary_label_ar": "نقص معروض / Supply Vacuum",
            "primary_score": 84,
            "drivers": [
                {"label_ar": "نقص معروض / Supply Vacuum"},
                {"label_ar": "اشتعال زخم وسيولة"},
            ],
        },
        "manipulation_risk": {
            "score": 58,
            "label": "HIGH",
            "label_ar": "مرتفع",
            "is_accusation": False,
        },
        "institutional_memory": {"acceleration": 71, "earlyness": 88, "anomaly": 69},
        "amplifiers": ["ضغط/قلة معروض 90/100"],
    }
    message = sender._stock_message(row)
    assert "نمط الانفجار" in message
    assert "Supply Vacuum" in message
    assert "WATCH" in message
    assert "علم خطر فقط" in message
    assert "ليس اتهامًا" in message


def test_stock_sender_sends_watch_then_confirmed_promotion(monkeypatch):
    sent: list[str] = []

    class Result:
        message_id = 10

    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text) or Result())
    monkeypatch.setenv("STOCK_WATCH_MIN_SCORE", "62")
    monkeypatch.setenv("STOCK_ALERT_MIN_SCORE", "72")
    monkeypatch.setenv("STOCK_ALERT_MAX", "0")

    watch = {
        "path": "stocks",
        "stocks": [{
            "symbol": "XYZ",
            "price": 4.0,
            "move_pct": 1.4,
            "stage": "PRESSURE_BUILDING",
            "alert_stage": "WATCH",
            "score": 66,
            "cause": {"status": "NO_PRIMARY_CAUSE_PROVEN", "status_ar": "غير مثبت"},
            "explosion_cause": {"primary": "SUPPLY_VACUUM", "primary_score": 80},
            "manipulation_risk": {"label": "LOW", "score": 10},
        }],
    }
    state = {"sent": {}}
    assert sender.send_stocks(watch, state) == 1
    assert state["sent"]["XYZ"]["alert_stage"] == "WATCH"

    confirmed = {
        "path": "stocks",
        "stocks": [{
            **watch["stocks"][0],
            "stage": "IGNITION",
            "alert_stage": "CONFIRMED",
            "score": 78,
        }],
    }
    assert sender.send_stocks(confirmed, state) == 1
    assert state["sent"]["XYZ"]["alert_stage"] == "CONFIRMED"
    assert len(sent) == 2


def test_stock_sender_zero_max_means_no_strategic_alert_cap(monkeypatch):
    sent: list[str] = []

    class Result:
        message_id = 1

    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text) or Result())
    monkeypatch.setenv("STOCK_ALERT_MIN_SCORE", "72")
    monkeypatch.setenv("STOCK_ALERT_MAX", "0")
    payload = {
        "path": "stocks",
        "stocks": [
            {
                "symbol": f"S{i}",
                "price": 5,
                "move_pct": 5,
                "stage": "IGNITION",
                "alert_stage": "CONFIRMED",
                "score": 80 + i,
                "cause": {"status": "OFFICIAL_CONFIRMED", "status_ar": "سبب رسمي"},
                "explosion_cause": {"primary": "CATALYST_REPRICING", "primary_score": 82},
                "manipulation_risk": {"label": "LOW", "score": 5},
            }
            for i in range(8)
        ],
    }
    state = {"sent": {}}
    assert sender.send_stocks(payload, state) == 8
    assert len(sent) == 8
