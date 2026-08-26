from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.thesis_engine import (
    BULLISH,
    build_thesis,
    classify_catalyst_reaction,
    select_contract_evidence,
)
from scripts.send_stock_intelligence_v10 import _message


def _classical(decision: str = "CALL", agreement: int = 100) -> dict:
    direction = "BULLISH" if decision == "CALL" else "BEARISH" if decision == "PUT" else "NEUTRAL"
    return {
        "decision": decision,
        "agreement_pct": agreement,
        "confirmation_level": 101.0,
        "invalidation_level": 97.0,
        "daily": {"direction": direction},
        "hourly": {"direction": direction},
        "intraday": {"direction": direction},
    }


def _catalyst() -> dict:
    return {
        "symbol": "XYZ",
        "score": 20,
        "headline": "Company wins material contract",
        "source": "SEC EDGAR",
        "url": "https://www.sec.gov/example",
    }


def _evidence(rank: int = 100) -> dict:
    return {"source_rank": rank, "attention_only": False}


def _live_contract() -> dict:
    return {
        "symbol": "XYZ",
        "contract_symbol": "XYZ260918C00105000",
        "option_type": "call",
        "strike": 105,
        "expiration": "2026-09-18",
        "bid": 2.00,
        "ask": 2.08,
        "spread_pct": 0.0385,
        "volume": 2200,
        "open_interest": 1400,
        "delta": 0.48,
        "iv": 0.42,
        "score": 91,
        "source": "licensed OPRA realtime",
        "freshness_label": "realtime",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_grade": "A",
    }


def test_confirmed_thesis_requires_aligned_multitimeframe_and_reaction() -> None:
    thesis = build_thesis(
        market_row={"symbol": "XYZ", "price": 100, "move_pct": 2.2, "relative_volume": 2.0, "stage": "IGNITION"},
        catalyst=_catalyst(),
        source_evidence=_evidence(),
        classical=_classical(),
        option_rows=[_live_contract()],
    )
    assert thesis.stage == "CONFIRMED"
    assert thesis.chart_grade in {"A+", "A"}
    assert thesis.manual_execution_ready is True
    assert thesis.data_confidence == "LIVE"
    assert thesis.contract.quote_age_seconds is not None
    assert thesis.contract.execution_blockers == ()


def test_classical_conflict_hard_fails_even_with_strong_catalyst() -> None:
    thesis = build_thesis(
        market_row={"symbol": "XYZ", "price": 100, "move_pct": 2.5, "relative_volume": 3.0, "stage": "IGNITION"},
        catalyst=_catalyst(),
        source_evidence=_evidence(),
        classical=_classical("PUT"),
        option_rows=[_live_contract()],
    )
    assert thesis.stage == "FAILED"
    assert thesis.overall_grade == "F"
    assert thesis.manual_execution_ready is False


def test_extended_reaction_prevents_chasing() -> None:
    reaction = classify_catalyst_reaction(
        {"move_pct": 11.0, "relative_volume": 4.0, "stage": "EXPLOSION"},
        BULLISH,
    )
    assert reaction.state == "EXTENDED"


def test_research_contract_can_be_displayed_but_not_execution_ready() -> None:
    contract = _live_contract()
    contract["source"] = "yahoo/yfinance"
    contract["freshness_label"] = "unofficial / may be delayed"
    evidence = select_contract_evidence([contract], symbol="XYZ", bias=BULLISH)
    assert evidence.available is True
    assert evidence.data_confidence == "RESEARCH"
    assert evidence.execution_ready is False


def test_live_label_without_absolute_quote_timestamp_is_not_execution_ready() -> None:
    contract = _live_contract()
    contract.pop("updated_at")
    contract["quote_age_seconds"] = 1.0
    evidence = select_contract_evidence([contract], symbol="XYZ", bias=BULLISH)
    assert evidence.data_confidence == "RESEARCH"
    assert evidence.execution_ready is False
    assert any("توقيت Quote" in blocker for blocker in evidence.execution_blockers)


def test_stale_live_quote_is_downgraded_to_research() -> None:
    contract = _live_contract()
    contract["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    evidence = select_contract_evidence([contract], symbol="XYZ", bias=BULLISH)
    assert evidence.data_confidence == "RESEARCH"
    assert evidence.execution_ready is False
    assert evidence.quote_age_seconds is not None and evidence.quote_age_seconds > 120


def test_delayed_marker_overrides_live_opra_words() -> None:
    contract = _live_contract()
    contract["source"] = "licensed OPRA realtime delayed"
    evidence = select_contract_evidence([contract], symbol="XYZ", bias=BULLISH)
    assert evidence.data_confidence == "RESEARCH"
    assert evidence.execution_ready is False


def test_fresh_live_contract_outranks_high_volume_research_contract() -> None:
    live = _live_contract()
    research = _live_contract()
    research["contract_symbol"] = "XYZ260918C00110000"
    research["strike"] = 110
    research["volume"] = 100000
    research["score"] = 99
    research["source"] = "yahoo/yfinance"
    research["freshness_label"] = "unofficial / may be delayed"
    evidence = select_contract_evidence([research, live], symbol="XYZ", bias=BULLISH)
    assert evidence.contract_symbol == live["contract_symbol"]
    assert evidence.execution_ready is True


def test_mobile_card_uses_evidence_grades_not_probability_score() -> None:
    thesis = build_thesis(
        market_row={"symbol": "XYZ", "price": 100, "move_pct": 2.2, "relative_volume": 2.0, "stage": "IGNITION"},
        catalyst=_catalyst(),
        source_evidence=_evidence(),
        classical=_classical(),
        option_rows=[_live_contract()],
    )
    message = _message(thesis)
    assert "1D" in message and "1H" in message and "15m" in message
    assert "البيانات <b>LIVE</b>" in message
    assert "Quote age" in message
    assert "/100" not in message
    assert "درجة الدليل" in message
