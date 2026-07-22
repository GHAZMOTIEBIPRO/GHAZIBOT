from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from options_radar.advanced_signals import (
    classify_13d_purpose,
    classify_dilution,
    is_standard_occ_contract,
    parse_form4_transactions,
)
from options_radar.calibration import build_calibration_report
from options_radar.indicators import TechnicalSnapshot
from options_radar.scanner import OptionsRadar
from options_radar.sectors import sector_context
from options_radar.settings import Settings
from options_radar.stocks import StockRadar
from options_radar import universe as universe_module


def test_form4_open_market_purchase_uses_disclosed_value() -> None:
    raw = """
    <ownershipDocument>
      <reportingOwner><reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship></reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>35000</value></transactionShares>
          <transactionPricePerShare><value>1.78</value></transactionPricePerShare>
        </transactionAmounts>
      </nonDerivativeTransaction></nonDerivativeTable>
    </ownershipDocument>
    """
    result = parse_form4_transactions(raw)
    assert result is not None
    assert result.category == "Insider open-market purchase"
    assert result.event_value == 62_300
    assert result.score >= 12
    assert result.confidence >= 0.9


def test_dilution_and_13d_classification() -> None:
    dilution = classify_dilution(
        "424B5",
        "We entered into an at-the-market equity distribution agreement to sell up to $25 million of common stock.",
    )
    assert dilution is not None
    assert dilution.score <= -24
    assert dilution.event_value == 25_000_000
    active = classify_13d_purpose(
        "Item 4 Purpose of Transaction. The reporting person may nominate directors and engage with the board regarding strategic alternatives."
    )
    assert active.score >= 18
    assert active.purpose == "active_or_control"


def test_occ_contract_guard_rejects_adjusted_roots() -> None:
    assert is_standard_occ_contract("AAPL260821C00330000", "AAPL") is True
    assert is_standard_occ_contract("AAPL1260821C00330000", "AAPL") is False
    assert is_standard_occ_contract("OLD260821C00330000", "AAPL") is False


def test_dynamic_universe_combines_sources_and_caps(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(universe_module, "sec_event_symbols", lambda settings: ["NEW1", "AAPL"])
    monkeypatch.setattr(universe_module, "nasdaq_mover_symbols", lambda: ["MOVE", "AAPL"])
    monkeypatch.setattr(universe_module, "_load_alias_symbols", lambda path="data/company_aliases.json": ["ALIAS"])
    settings = Settings(max_universe_size=5, database_path=tmp_path / "state.json")
    symbols, sources = universe_module.build_dynamic_universe(["AAPL", "MSFT"], settings)
    assert symbols == ["AAPL", "MSFT", "NEW1", "MOVE", "ALIAS"]
    assert sources["total"] == 5


def test_unknown_sector_is_neutral_without_network() -> None:
    result = sector_context("UNKNOWN_TEST", pd.DataFrame({"Close": range(30)}))
    assert result["sector_score"] == 0
    assert result["sector_etf"] == "SPY"


def test_adjusted_contract_is_reported_as_rejected(tmp_path) -> None:
    settings = Settings(
        provider="yahoo",
        database_path=tmp_path / "state.json",
        min_option_volume=1,
        min_open_interest=1,
    )
    radar = OptionsRadar(settings)
    chain = pd.DataFrame([
        {
            "contract_symbol": "AAPL1260821C00330000",
            "symbol": "AAPL",
            "expiration": pd.Timestamp("2026-08-21"),
            "strike": 330.0,
            "option_type": "call",
            "bid": 1.0,
            "ask": 1.1,
            "volume": 100,
            "open_interest": 100,
            "data_quality": 0.9,
            "updated_at": datetime.now(timezone.utc),
            "source": "test",
            "freshness_label": "test",
        }
    ])
    rejected = radar._rejection_rows(chain, pd.DataFrame())
    assert rejected.iloc[0]["rejection_reason"] == "adjusted_or_nonstandard_contract"


def _technical() -> TechnicalSnapshot:
    return TechnicalSnapshot(
        symbol="TEST", close=110.0, ema9=108.0, ema21=106.0, ema50=100.0,
        ema200=90.0, rsi14=60.0, macd=2.0, macd_signal=1.0, atr14=2.0,
        realized_vol20=0.3, relative_volume20=2.0, resistance20=100.0,
        support20=95.0, direction="bullish", catalyst="test", catalyst_score=15,
        breakout=True,
    )


def test_late_entry_and_dilution_are_rejected() -> None:
    history = pd.DataFrame({"Close": [100.0] * 25, "Volume": [1_000_000] * 25})
    row = StockRadar._score(
        "TEST", _technical(), history, "risk_on",
        {
            "score": -24,
            "category": "Active ATM offering",
            "headline": "ATM",
            "purpose": "dilution",
            "confidence": 0.95,
        },
    )
    assert row["entry_state"] == "too_late"
    assert "price_extended" in row["rejection_reason"]


def test_calibration_waits_for_minimum_sample(tmp_path) -> None:
    signals = tmp_path / "signals.jsonl"
    outcomes = tmp_path / "outcomes.json"
    signals.write_text(
        json.dumps({"signal_id": "a", "score": 75, "catalyst": "FDA: approval"}) + "\n",
        encoding="utf-8",
    )
    outcomes.write_text(
        json.dumps({"signals": {"a": {"observations": 2, "mfe_pct": 20, "mae_pct": -10, "target_1_observed": True, "target_2_observed": False, "stop_observed": False}}}),
        encoding="utf-8",
    )
    report = build_calibration_report(signals, outcomes, minimum_sample=100)
    assert report["priced_sample"] == 1
    assert report["calibration_ready"] is False
    assert "99 more" in report["decision"]


def test_public_page_contains_rejected_and_calibration_sections() -> None:
    html = Path("public/index.html").read_text(encoding="utf-8")
    javascript = Path("public/app.js").read_text(encoding="utf-8")
    assert 'data-tab="rejected"' in html
    assert 'data-tab="results"' in html
    assert "renderRejected" in javascript
    assert "renderCalibration" in javascript
