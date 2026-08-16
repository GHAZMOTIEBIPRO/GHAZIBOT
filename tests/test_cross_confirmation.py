from __future__ import annotations

from datetime import datetime, timezone

import scripts.send_cross_confirmation as cross


def _payloads():
    now = datetime.now(timezone.utc).isoformat()
    stocks = {
        "generated_at": now,
        "stocks": [
            {
                "symbol": "XYZ",
                "price": 101,
                "move_pct": 3.2,
                "stage": "IGNITION",
                "score": 81,
                "cause": {"status_ar": "محفز مثبت"},
            }
        ],
    }
    options = {
        "generated_at": now,
        "provider_readiness": {"production_quote_ready": True, "status": "LIVE_FLOW_READY"},
        "contracts": [
            {
                "symbol": "XYZ",
                "contract_symbol": "XYZ260918C00100000",
                "option_type": "CALL",
                "expiration": "2026-09-18",
                "strike": 100,
                "bid": 4.9,
                "ask": 5.1,
                "score": 86,
                "flow_momentum_score": 90,
                "flow_rank_score": 91,
            }
        ],
    }
    return stocks, options


def test_cross_confirmation_only_matches_same_symbol():
    stocks = {
        "stocks": [
            {"symbol": "AAA", "score": 80, "stage": "IGNITION"},
            {"symbol": "BBB", "score": 75, "stage": "IGNITION"},
        ]
    }
    options = {
        "contracts": [
            {"symbol": "AAA", "contract_symbol": "AAA1", "score": 70, "flow_momentum_score": 80},
            {"symbol": "CCC", "contract_symbol": "CCC1", "score": 90, "flow_momentum_score": 95},
        ]
    }
    matches = cross.build_matches(stocks, options)
    assert [row["symbol"] for row in matches] == ["AAA"]


def test_cross_confirmation_edits_existing_option_card_instead_of_sending_new(monkeypatch):
    stocks, options = _payloads()
    edits = []

    class EditResult:
        attempts = 1

    monkeypatch.setattr(
        cross,
        "edit_html_message",
        lambda message_id, text: edits.append((message_id, text)) or EditResult(),
    )
    state = {"sent": {}}
    stock_alert_state = {
        "sent": {
            "XYZ": {
                "message_id": 11,
                "text": "🚀 <b>Ω | XYZ stock</b>",
                "sent_at": "2026-08-17T00:00:00+00:00",
                "symbol": "XYZ",
            }
        }
    }
    options_alert_state = {
        "sent": {
            "XYZ:CALL": {
                "message_id": 22,
                "text": "🟢 <b>Ω | XYZ CALL</b>",
                "sent_at": "2026-08-17T00:01:00+00:00",
                "symbol": "XYZ",
                "direction": "CALL",
            }
        }
    }

    updated = cross.send_matches(
        stocks,
        options,
        state,
        stock_alert_state=stock_alert_state,
        options_alert_state=options_alert_state,
    )
    assert updated == 1
    assert len(edits) == 1
    assert edits[0][0] == 22
    assert "تأكيد مستقل" in edits[0][1]
    assert "CALL" in edits[0][1]
    assert state["last_sent_count"] == 0
    assert state["last_edited_count"] == 1
    assert state["delivery_policy"] == "edit_existing_opportunity_message_only"


def test_cross_confirmation_never_creates_third_message_without_registry(monkeypatch):
    stocks, options = _payloads()
    edits = []
    monkeypatch.setattr(cross, "edit_html_message", lambda *a, **k: edits.append((a, k)))
    state = {"sent": {}}
    updated = cross.send_matches(stocks, options, state, stock_alert_state={}, options_alert_state={})
    assert updated == 0
    assert edits == []
    assert state["last_sent_count"] == 0
    assert state["skipped_without_message_registry"] == 1


def test_cross_confirmation_falls_back_to_stock_card_when_no_option_card(monkeypatch):
    stocks, options = _payloads()
    edits = []

    class EditResult:
        attempts = 2

    monkeypatch.setattr(
        cross,
        "edit_html_message",
        lambda message_id, text: edits.append((message_id, text)) or EditResult(),
    )
    state = {"sent": {}}
    stock_alert_state = {
        "sent": {
            "XYZ": {
                "message_id": 44,
                "text": "🚀 <b>Ω | XYZ</b>",
                "sent_at": "2026-08-17T00:00:00+00:00",
                "symbol": "XYZ",
            }
        }
    }
    assert cross.send_matches(
        stocks,
        options,
        state,
        stock_alert_state=stock_alert_state,
        options_alert_state={},
    ) == 1
    assert edits[0][0] == 44
    assert state["sent"]["XYZ"]["telegram_edit_attempts"] == 2


def test_cross_confirmation_blocks_fallback_only_options(monkeypatch):
    stocks, options = _payloads()
    options["provider_readiness"] = {
        "status": "FALLBACK_ONLY",
        "production_quote_ready": False,
        "production_flow_ready": False,
    }
    edits = []
    monkeypatch.setattr(cross, "edit_html_message", lambda *a, **k: edits.append((a, k)))
    state = {"sent": {}}
    assert cross.send_matches(stocks, options, state) == 0
    assert edits == []
    assert state["blocked_reason"] == "FALLBACK_ONLY"


def test_direction_alignment_is_explained_in_arabic():
    assert "متوافق" in cross._alignment(4.0, "CALL")
    assert "متوافق" in cross._alignment(-4.0, "PUT")
    assert "غير متوافق" in cross._alignment(4.0, "PUT")
