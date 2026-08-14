from datetime import datetime, timezone

import scripts.send_cross_confirmation as cross


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


def test_cross_confirmation_blocks_fallback_only_options(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(cross, "_send", sent.append)
    now = datetime.now(timezone.utc).isoformat()
    stocks = {
        "generated_at": now,
        "stocks": [{"symbol": "AAA", "score": 85, "stage": "IGNITION", "move_pct": 5}],
    }
    options = {
        "generated_at": now,
        "provider_readiness": {
            "status": "FALLBACK_ONLY",
            "production_quote_ready": False,
            "production_flow_ready": False,
        },
        "contracts": [
            {
                "symbol": "AAA",
                "contract_symbol": "AAA1",
                "option_type": "call",
                "score": 90,
                "flow_momentum_score": 90,
            }
        ],
    }
    state = {"sent": {}}
    assert cross.send_matches(stocks, options, state) == 0
    assert sent == []
    assert state["blocked_reason"] == "FALLBACK_ONLY"


def test_direction_alignment_is_explained_in_arabic():
    assert "متوافق" in cross._alignment(4.0, "CALL")
    assert "متوافق" in cross._alignment(-4.0, "PUT")
    assert "غير متوافق" in cross._alignment(4.0, "PUT")
