from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.data_fabric import (
    FabricAttempt,
    ProviderHealthRegistry,
    health_from_env,
    reconcile_option_chains,
    reconcile_stock_bars,
)
from options_radar.options_consensus import build_directional_signals


CONTRACT = "XYZ260918C00100000"


def _chain_row(bid: float, ask: float, quality: float, source: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_symbol": CONTRACT,
                "symbol": "XYZ",
                "expiration": "2026-09-18",
                "strike": 100.0,
                "option_type": "call",
                "bid": bid,
                "ask": ask,
                "last": (bid + ask) / 2,
                "volume": 2000,
                "open_interest": 1500,
                "iv": 0.45,
                "delta": 0.50,
                "gamma": 0.04,
                "theta": -0.02,
                "vega": 0.08,
                "underlying_price": 101.0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "data_quality": quality,
                "freshness_label": "account feed",
            }
        ]
    )


def test_option_reconciliation_keeps_bid_ask_from_one_provider():
    frames = {
        "provider_a": _chain_row(1.00, 1.10, 0.80, "provider_a"),
        "provider_b": _chain_row(1.20, 1.30, 0.90, "provider_b"),
    }
    out, audit = reconcile_option_chains(
        frames,
        freshness={"provider_a": "account feed", "provider_b": "account feed"},
        max_quote_divergence_pct=0.08,
    )
    assert len(out) == 1
    row = out.iloc[0]
    assert row["bid"] == 1.20
    assert row["ask"] == 1.30
    assert row["fabric_quote_provider"] == "provider_b"
    assert row["fabric_source_count"] == 2
    assert row["fabric_consensus_pass"] is False or bool(row["fabric_consensus_pass"]) is False
    assert audit["max_quote_divergence_pct"] > 0.08


def test_option_reconciliation_rewards_agreement_without_synthesizing_quote():
    frames = {
        "tradier": _chain_row(1.00, 1.10, 0.90, "tradier"),
        "alpaca": _chain_row(1.01, 1.11, 0.88, "alpaca"),
    }
    out, audit = reconcile_option_chains(
        frames,
        freshness={"tradier": "brokerage feed", "alpaca": "OPRA real-time"},
    )
    row = out.iloc[0]
    assert row["bid"] == 1.00
    assert row["ask"] == 1.10
    assert bool(row["fabric_consensus_pass"]) is True
    assert row["fabric_independent_source_count"] == 2
    assert audit["consensus_contracts"] == 1


def test_stock_reconciliation_selects_one_intact_series():
    index = pd.to_datetime(["2026-08-14T14:00:00Z", "2026-08-14T14:05:00Z"])
    tradier = pd.DataFrame(
        {
            "Open": [99.0, 100.0],
            "High": [101.0, 102.0],
            "Low": [98.0, 99.0],
            "Close": [100.0, 101.0],
            "Volume": [1000, 1200],
        },
        index=index,
    )
    yahoo = tradier.copy()
    yahoo["Close"] = [100.0, 100.9]
    selected, source, audit = reconcile_stock_bars(
        {"tradier": tradier, "yahoo": yahoo},
        freshness={"tradier": "brokerage feed", "yahoo": "unofficial / may be delayed"},
    )
    assert source == "tradier"
    assert list(selected["Close"]) == [100.0, 101.0]
    assert audit["source_count"] == 2


def test_provider_health_opens_and_recovers_circuit(tmp_path):
    registry = ProviderHealthRegistry(
        tmp_path / "health.json",
        failure_threshold=3,
        cool_down_minutes=5,
    )
    for _ in range(3):
        registry.record(
            FabricAttempt(
                provider="finnhub",
                operation="option_chain",
                success=False,
                elapsed_ms=50,
                error="HTTP 429",
            )
        )
    assert registry.allowed("finnhub", "option_chain") is False
    assert registry.allowed(
        "finnhub",
        "option_chain",
        now=datetime.now(timezone.utc) + timedelta(minutes=6),
    ) is True


def test_health_from_env_is_process_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FABRIC_HEALTH_PATH", str(tmp_path / "singleton.json"))
    monkeypatch.setenv("DATA_FABRIC_CIRCUIT_FAILURES", "3")
    monkeypatch.setenv("DATA_FABRIC_CIRCUIT_MINUTES", "20")
    assert health_from_env() is health_from_env()


def test_provider_quote_disagreement_is_hard_options_blocker():
    row = {
        "symbol": "XYZ",
        "contract_symbol": CONTRACT,
        "option_type": "call",
        "score": 99,
        "flow_momentum_score": 99,
        "data_quality": 0.95,
        "execution_score": 30,
        "reward_risk_1": 2.0,
        "spread_pct": 0.03,
        "vol_to_oi_ratio": 4.0,
        "volume": 5000,
        "open_interest": 5000,
        "delta": 0.50,
        "dte": 28,
        "gamma_concentration_pct": 20,
        "gamma_context_alignment": 0.3,
        "gamma_coverage_pct": 95,
        "oi_coverage_pct": 95,
        "occ_side_context": {"available": False, "bonus": 0},
        "fabric_independent_source_count": 2,
        "fabric_quote_divergence_pct": 0.18,
        "fabric_consensus_pass": False,
    }
    assert build_directional_signals([row], minimum_score=70) == []
