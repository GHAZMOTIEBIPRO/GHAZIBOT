from datetime import datetime, timezone

from scripts import send_omega_watch_alerts as sender


def _payload(stage: str = "WATCH"):
    primary = {
        "symbol": "XYZ",
        "contract_symbol": "XYZ261016C00100000",
        "side": "CALL",
        "expiration": "2026-10-16",
        "dte": 14,
        "strike": 100,
        "bid": 1.0,
        "ask": 1.1,
        "spread_pct": 0.09,
        "delta": 0.46,
        "gamma": 0.05,
        "iv": 0.7,
        "vol_to_oi_ratio": 2.2,
        "contract_rank": 82,
        "side_reason_ar": "الاتجاه الفني صاعد",
        "expiry_reason_ar": "أفق الهدف 1–3 جلسات",
        "flow_reason_ar": "النشاط يتسارع لكن دون إثبات sweep",
        "risks_ar": [],
        "alert_stage": stage,
        "watch_decision": {
            "approved": stage == "WATCH",
            "evidence_score": 82,
            "production_claim": False,
        },
        "option_explosion": {"score": 76, "label": "BUILDING"},
        "v11_decision": {
            "approved": False,
            "blockers": ["v11_independent_source_quorum_not_met"],
        },
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "option_contract_intelligence": {
            "by_symbol": {
                "XYZ": {
                    "target_dte": 10,
                    "preferred_dte_band": [7, 14],
                    "primary": primary,
                }
            }
        },
    }


def test_rows_only_include_watch_stage():
    rows = sender._rows(_payload("WATCH"))
    assert len(rows) == 1
    assert rows[0]["_symbol"] == "XYZ"
    assert sender._rows(_payload("CONFIRMED")) == []


def test_watch_sender_sends_and_deduplicates(monkeypatch):
    sent = []

    class Result:
        message_id = 123

    monkeypatch.setattr(sender, "send_html_message", lambda text: sent.append(text) or Result())
    state = {"sent": {}}
    assert sender.send(_payload(), state) == 1
    assert "مراقبة مبكرة OPTIONS" in sent[0]
    assert "WATCH فقط" in sent[0]
    assert state["sent"]["WATCH:XYZ:CALL"]["message_id"] == 123
    assert sender.send(_payload(), state) == 0
