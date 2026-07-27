from __future__ import annotations

import pandas as pd

from options_radar.flow_analyzer import FlowAnalyzer, FlowThresholds


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_symbol": "AAPL260116C00200000",
                "symbol": "AAPL",
                "option_type": "call",
                "bid": 2.00,
                "ask": 2.20,
                "last": 2.18,
                "volume": 900,
                "open_interest": 200,
                "delta": 0.45,
                "dte": 35,
                "quality_passed": True,
                "rejection_reason": "",
            },
            {
                "contract_symbol": "AAPL260116P00150000",
                "symbol": "AAPL",
                "option_type": "put",
                "bid": 1.00,
                "ask": 1.20,
                "last": 1.01,
                "volume": 1000,
                "open_interest": 200,
                "delta": -0.45,
                "dte": 35,
                "quality_passed": True,
                "rejection_reason": "",
            },
        ]
    )


def test_high_accumulation_ask_side_contract_passes_without_history():
    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        _chain(), technical_direction="bullish"
    )
    assert len(result.accepted) == 1
    row = result.accepted.iloc[0]
    assert row["vol_to_oi_ratio"] == 4.5
    assert row["buying_flow_type"] == "Aggressive Buying"
    assert bool(row["unusual_activity_flag"]) is True


def test_bid_side_trade_is_rejected_as_selling_pressure_proxy():
    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        _chain(), technical_direction="bullish"
    )
    put = result.rejected[
        result.rejected["option_type"] == "put"
    ].iloc[0]
    assert put["rejection_reason"] == "bid_side_or_neutral_trade"
    assert put["buying_flow_type"] == "Neutral"


def test_zero_open_interest_never_divides_by_zero():
    chain = _chain().iloc[[0]].copy()
    chain.loc[:, "open_interest"] = 0
    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(chain)
    assert result.accepted.empty
    assert pd.isna(result.rejected.iloc[0]["vol_to_oi_ratio"])
    assert (
        result.rejected.iloc[0]["rejection_reason"]
        == "open_interest_below_100"
    )


def test_volume_history_confirms_two_hundred_percent_spike():
    chain = _chain().iloc[[0]].copy()
    chain.loc[:, "volume"] = 400
    chain.loc[:, "open_interest"] = 200

    def history_loader(_contract: str) -> pd.DataFrame:
        index = pd.date_range(
            "2026-07-20", periods=5, freq="D", tz="UTC"
        )
        return pd.DataFrame(
            {"Volume": [100, 100, 100, 100, 100]},
            index=index,
        )

    result = FlowAnalyzer(thresholds=FlowThresholds()).analyze(
        chain,
        technical_direction="bullish",
        history_loader=history_loader,
    )
    row = result.accepted.iloc[0]
    assert row["volume_spike_ratio"] == 4.0
    assert bool(row["volume_spike_flag"]) is True


def test_top_by_side_returns_independent_limits():
    frame = pd.DataFrame(
        [
            {
                "option_type": "call",
                "flow_rank_score": 90 - index,
                "contract_symbol": f"C{index}",
            }
            for index in range(20)
        ]
        + [
            {
                "option_type": "put",
                "flow_rank_score": 80 - index,
                "contract_symbol": f"P{index}",
            }
            for index in range(20)
        ]
    )
    calls, puts = FlowAnalyzer.top_by_side(frame, limit=15)
    assert len(calls) == 15
    assert len(puts) == 15
    assert calls.iloc[0]["contract_symbol"] == "C0"
    assert puts.iloc[0]["contract_symbol"] == "P0"
