from __future__ import annotations

import os

import scripts.send_independent_path_alerts as sender


def test_option_message_never_claims_sweep_or_opening_from_snapshot():
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
    }
    message = sender._option_message(row)
    assert "Sweep:</b> غير مؤكد" in message
    assert "Opening position:</b> غير مؤكد" in message
    assert "لا ينتظر إشارة من مسار الأسهم" in message


def test_stock_message_says_options_are_not_required():
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
    assert "مسار الأسهم" in message
    assert "لا يحتاج وجود عقود أوبشن" in message


def test_options_sender_deduplicates_by_contract(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sender, "_send", sent.append)
    monkeypatch.setenv("OPTIONS_ALERT_MIN_SCORE", "65")
    payload = {
        "path": "options",
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


def test_stock_sender_does_not_read_options_fields(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(sender, "_send", sent.append)
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
