from __future__ import annotations

from options_radar.event_source_policy import event_source_evidence
from options_radar.intrinio_flow import enrich_with_intrinio_flow
from scripts import send_options_intelligence_v7 as options_v7
from scripts import send_stock_intelligence_v7 as stock_v7


class FakeIntrinio:
    enabled = True

    def recent_by_contract(self, symbol: str):
        assert symbol == "NVDA"
        return {
            "NVDA260828C00190000": [
                {
                    "contract": "NVDA260828C00190000",
                    "timestamp": "2026-08-25T14:00:00+00:00",
                    "type": "sweep",
                    "total_value": 350000,
                    "total_size": 800,
                    "average_price": 4.38,
                    "ask_at_execution": 4.40,
                    "bid_at_execution": 4.30,
                    "sentiment": "bullish",
                    "underlying_price_at_execution": 188.5,
                }
            ]
        }


def test_trade_level_flow_can_confirm_sweep_but_never_buy_to_open() -> None:
    rows, errors = enrich_with_intrinio_flow(
        [
            {
                "symbol": "NVDA",
                "contract_symbol": "NVDA260828C00190000",
                "option_type": "call",
                "flow_evidence": {"opening_position_confirmed": False},
            }
        ],
        client=FakeIntrinio(),
        max_symbols=3,
    )
    assert errors == {}
    row = rows[0]
    assert row["verified_trade_flow"] is True
    assert row["sweep_confirmed"] is True
    assert row["buy_to_open_confirmed"] is False
    assert row["opening_position_confirmed"] is False
    assert row["flow_evidence"]["trade_quote_level_evidence"] is True
    assert row["flow_evidence"]["opening_position_confirmed"] is False


def test_verified_bullish_call_flow_receives_verified_tier() -> None:
    flow = options_v7._flow_assessment(
        {
            "direction": "CALL",
            "verified_trade_flow": True,
            "verified_unusual_sentiment": "bullish",
            "verified_unusual_type": "sweep",
            "verified_unusual_total_value": 500000,
            "verified_unusual_print_count": 2,
            "volume": 1000,
            "open_interest": 200,
            "vol_oi": 5.0,
        }
    )
    assert flow["tier"] == "VERIFIED"
    assert flow["verified"] is True
    assert flow["score"] >= 90


def test_snapshot_volume_over_oi_is_not_labeled_verified_buying() -> None:
    flow = options_v7._flow_assessment(
        {
            "direction": "CALL",
            "volume": 1200,
            "open_interest": 300,
            "vol_oi": 4.0,
            "flow_momentum_score": 80,
            "flow_evidence": {"execution_pressure_proxy": "ask"},
        }
    )
    assert flow["tier"] == "SNAPSHOT_PROXY"
    assert flow["verified"] is False
    assert "غير مؤكد" in flow["label"]


def test_attention_only_news_cannot_create_strong_stock_news_alert() -> None:
    row = {
        "score": 95,
        "stage": "EXPLOSION",
        "move_pct": 18,
        "turnover_pct": 5,
        "volume": 10_000_000,
    }
    catalyst = {
        "score": 25,
        "source": "Reddit",
        "url": "https://reddit.com/example",
        "category": "rumor",
    }
    evidence = event_source_evidence(catalyst)
    assert evidence["attention_only"] is True
    assert stock_v7._strong_enough(row, catalyst, evidence) is False


def test_official_sec_news_can_qualify_with_market_confirmation() -> None:
    row = {
        "score": 74,
        "stage": "IGNITION",
        "move_pct": 3.2,
        "turnover_pct": 0.7,
        "volume": 1_200_000,
    }
    catalyst = {
        "score": 20,
        "source": "SEC EDGAR",
        "url": "https://www.sec.gov/example",
        "category": "Strategic contract",
    }
    evidence = event_source_evidence(catalyst)
    assert evidence["source_tier"] == "A_OFFICIAL"
    assert stock_v7._strong_enough(row, catalyst, evidence) is True


def test_oi_followup_requires_next_date_and_material_increase(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(options_v7, "send_html_message", lambda text: messages.append(text))
    state = {
        "sent": {},
        "contracts": {
            "NVDA260828C00190000": {
                "symbol": "NVDA",
                "direction": "CALL",
                "sent_date": "2026-08-24",
                "baseline_oi": 1000,
                "baseline_volume": 2000,
                "oi_followup_sent": False,
            }
        },
    }
    payload = {
        "contracts": [
            {
                "symbol": "NVDA",
                "direction": "CALL",
                "contract_symbol": "NVDA260828C00190000",
                "open_interest": 1350,
            }
        ]
    }
    sent = options_v7._send_oi_followups(payload, state)
    assert sent == 1
    assert len(messages) == 1
    assert "لا تثبت هوية المتداول" in messages[0]
    assert state["contracts"]["NVDA260828C00190000"]["oi_followup_sent"] is True
