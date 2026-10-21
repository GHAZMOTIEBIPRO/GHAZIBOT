"""Offline regression for calendar-adjusted contract volume research context."""
from __future__ import annotations

import pandas as pd

from options_radar.calendar_volume_context import calendar_adjusted_contract_volume
from options_radar.flow_analyzer import FlowAnalyzer, FlowThresholds
from options_radar.option_anomaly import analyze_contract_volume_anomaly

OBS = "2026-10-21T16:00:00Z"
EXPIRY = "2026-12-31"


def history() -> pd.DataFrame:
    index = pd.bdate_range("2026-08-03", "2026-10-20", tz="America/New_York")
    return pd.DataFrame({"Volume": [100.0] * len(index)}, index=index)


def test_matching_weekday_and_expiry_band_never_claims_execution():
    result = calendar_adjusted_contract_volume(
        500, history(), observed_at=OBS, expiration=EXPIRY,
    )
    assert result["available"] is True
    assert result["ratio"] == 5
    assert result["historical_median"] == 100
    assert result["joint_observations"] >= 3
    assert result["dte_band"] == "DTE_31_PLUS"
    assert result["research_only"] is True
    assert result["decision_authority"] is False
    assert result["score_adjustment"] == 0.0


def test_current_expiry_does_not_borrow_histories_from_other_dte():
    result = calendar_adjusted_contract_volume(
        500, history(), observed_at=OBS, expiration="2026-10-21",
    )
    assert result["available"] is False
    assert result["reason"] == "INSUFFICIENT_MATCHED_HISTORY"
    assert result["ratio"] is None


def test_datetime_provenance_and_numeric_validation_fail_closed():
    assert calendar_adjusted_contract_volume(
        500, history(), observed_at="2026-10-21", expiration=EXPIRY,
    )["reason"] == "MISSING_DATED_PROVENANCE"
    assert calendar_adjusted_contract_volume(
        -1, history(), observed_at=OBS, expiration=EXPIRY,
    )["reason"] == "INVALID_VOLUME"
    assert calendar_adjusted_contract_volume(
        500, history(), observed_at=OBS, expiration="2026-01-01",
    )["reason"] == "EXPIRED_CONTRACT"


def test_normalizer_does_not_raise_existing_anomaly_score():
    base = analyze_contract_volume_anomaly(500, history())
    extra = analyze_contract_volume_anomaly(
        500, history(), observed_at=OBS, expiration=EXPIRY,
    )
    assert extra.ready == base.ready
    assert extra.score == base.score
    assert extra.calendar_volume is not None
    assert extra.calendar_volume["available"] is True


def test_flow_integration_is_research_metadata_only():
    chain = pd.DataFrame([{
        "symbol": "TEST", "contract_symbol": "TEST261231C00100000",
        "option_type": "call", "bid": 1.00, "ask": 1.10, "last": 1.09,
        "volume": 500, "open_interest": 200, "delta": 0.45, "dte": 71,
        "quality_passed": True, "last_trade_timestamp": OBS,
        "expiration": EXPIRY,
    }])
    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        chain, technical_direction="bullish", history_loader=lambda _: history(),
    )
    assert len(result.accepted) == 1
    row = result.accepted.iloc[0]
    assert row["historical_calendar_context"]["available"] is True
    assert row["historical_calendar_context"]["ratio"] == 5
    assert bool(row["flow_gate_pass"]) is True
    assert result.summary["historical_volume_anomalies"] == 1
