from __future__ import annotations

import pandas as pd

from options_radar.flow_analyzer import FlowAnalyzer, FlowThresholds
from options_radar.option_anomaly import analyze_contract_volume_anomaly


def _history(values: list[int]) -> pd.DataFrame:
    index = pd.date_range("2026-09-01", periods=len(values), freq="B", tz="UTC")
    return pd.DataFrame({"Volume": values}, index=index)


def test_contract_volume_anomaly_uses_contract_specific_history():
    profile = analyze_contract_volume_anomaly(
        500,
        _history([90, 100, 110, 95, 105, 100, 98, 102]),
    )

    assert profile.ready is True
    assert profile.observations == 8
    assert profile.volume_to_median_ratio is not None
    assert profile.volume_to_median_ratio >= 4.5
    assert profile.empirical_percentile == 1.0
    assert profile.score >= 80


def test_flow_analyzer_adds_historical_anomaly_without_replacing_strict_gate():
    chain = pd.DataFrame(
        [
            {
                "contract_symbol": "TEST261120C00100000",
                "symbol": "TEST",
                "option_type": "call",
                "bid": 1.00,
                "ask": 1.10,
                "last": 1.09,
                "volume": 500,
                "open_interest": 200,
                "delta": 0.45,
                "dte": 35,
                "quality_passed": True,
                "rejection_reason": "",
            }
        ]
    )

    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        chain,
        technical_direction="bullish",
        history_loader=lambda _contract: _history(
            [90, 100, 110, 95, 105, 100, 98, 102]
        ),
    )

    assert len(result.accepted) == 1
    row = result.accepted.iloc[0]
    assert bool(row["flow_gate_pass"]) is True
    assert bool(row["historical_volume_anomaly_flag"]) is True
    assert row["historical_volume_anomaly_score"] >= 80
    assert row["flow_historical_anomaly_bonus"] > 0
    assert result.summary["historical_volume_anomalies"] == 1


def test_historical_anomaly_does_not_bypass_vol_oi_requirement():
    chain = pd.DataFrame(
        [
            {
                "contract_symbol": "TEST261120C00100000",
                "symbol": "TEST",
                "option_type": "call",
                "bid": 1.00,
                "ask": 1.10,
                "last": 1.09,
                "volume": 500,
                "open_interest": 2_000,
                "delta": 0.45,
                "dte": 35,
                "quality_passed": True,
                "rejection_reason": "",
            }
        ]
    )

    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        chain,
        technical_direction="bullish",
        history_loader=lambda _contract: _history(
            [20, 20, 20, 20, 20, 20, 20, 20]
        ),
    )

    assert result.accepted.empty
    assert result.rejected.iloc[0]["rejection_reason"] == "vol_to_oi_below_1_5"
