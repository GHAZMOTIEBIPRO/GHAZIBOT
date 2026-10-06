"""Regression tests for data integrity, consensus, and timestamp honesty."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from options_radar.data_fabric import _provider_family, reconcile_option_chains, reconcile_stock_bars
from options_radar.execution_confidence import assess_execution_quote


NOW = datetime(2026, 10, 3, 14, 0, 0, tzinfo=timezone.utc)
CONTRACT = "XYZ261120C00100000"


def _option_frame(
    provider: str,
    bid: float = 1.0,
    ask: float = 1.1,
    quote_timestamp: str | None = None,
    updated_at: str | None = None,
    generated_at: str | None = None,
) -> pd.DataFrame:
    """Build a minimal options frame for testing."""
    return pd.DataFrame(
        [
            {
                "contract_symbol": CONTRACT,
                "symbol": "XYZ",
                "expiration": "2026-11-20",
                "strike": 100.0,
                "option_type": "call",
                "bid": bid,
                "ask": ask,
                "volume": 1000,
                "open_interest": 800,
                "iv": 0.4,
                "delta": 0.5,
                "data_quality": 0.85,
                "quote_timestamp": quote_timestamp,
                "updated_at": updated_at or "2026-10-03T13:59:30Z",
                "generated_at": generated_at,
                "timestamp_kind": "quote" if quote_timestamp else None,
            }
        ]
    )


def _stock_frame(provider: str, close: float = 101.5, timestamp: str | None = None) -> pd.DataFrame:
    """Build a minimal stock bars frame for testing."""
    if timestamp is None:
        timestamp = "2026-10-02"
    return pd.DataFrame(
        {"Close": [close, close * 0.99, close * 1.01]},
        index=pd.date_range(timestamp, periods=3, freq="D", tz="UTC"),
    )


# ============================================================================
# TIMESTAMP INTEGRITY TESTS
# ============================================================================


def test_quote_timestamp_old_received_at_now_is_stale() -> None:
    """Test case 1: quote_timestamp=old, received_at=now => STALE.
    
    Proves that a recent received_at does NOT make an old quote fresh.
    """
    old_quote = (NOW - timedelta(minutes=5)).isoformat()
    gate = assess_execution_quote(
        {
            "source": "licensed OPRA",
            "quote_timestamp": old_quote,
            "bid": 2.0,
            "ask": 2.1,
            # received_at would be NOW, but quote_timestamp is 5 minutes old
        },
        now=NOW,
        max_quote_age_seconds=120.0,
    )
    # Quote is 300 seconds old, exceeds 120s max
    assert gate.execution_ready is False
    assert gate.confidence == "RESEARCH"
    assert gate.quote_age_seconds == pytest.approx(300, abs=1)


def test_generated_at_now_quote_timestamp_missing_not_execution_ready() -> None:
    """Test case 2: generated_at=now, quote_timestamp missing => NOT EXECUTION-READY.
    
    Proves that generated timestamp cannot substitute for quote timestamp.
    """
    gate = assess_execution_quote(
        {
            "source": "licensed quote feed",
            "generated_at": NOW.isoformat(),
            "quote_timestamp": None,  # Explicitly missing
            "bid": 2.0,
            "ask": 2.1,
            "timestamp_kind": "generated",
        },
        now=NOW,
    )
    assert gate.execution_ready is False
    assert gate.confidence == "RESEARCH"
    assert any("توقيت Quote" in b for b in gate.blockers)


# ============================================================================
# PROVIDER FAMILY NORMALIZATION TESTS
# ============================================================================


def test_provider_family_yahoo_variants_all_map_to_yahoo() -> None:
    """Test that all Yahoo transport variants map to one family."""
    assert _provider_family("yahoo") == "yahoo"
    assert _provider_family("yfinance") == "yahoo"
    assert _provider_family("yahooquery") == "yahoo"
    assert _provider_family("YAHOO/YFINANCE") == "yahoo"
    assert _provider_family("YfinancE") == "yahoo"


def test_yahoo_yfinance_independent_source_count_is_one() -> None:
    """Test case 3: Yahoo + yfinance => independent_source_count = 1."""
    out, audit = reconcile_option_chains(
        {
            "yahoo": _option_frame("yahoo", bid=1.0, ask=1.1),
            "yfinance": _option_frame("yfinance", bid=1.01, ask=1.11),
        },
        freshness={
            "yahoo": "unofficial / may be delayed",
            "yfinance": "unofficial / may be delayed",
        },
    )
    row = out.iloc[0]
    assert row["fabric_source_count"] == 2, "Two transport sources"
    assert row["fabric_independent_source_count"] == 1, "One family"
    assert audit["transport_source_count"] == 2
    assert audit["independent_source_count"] == 1
    assert audit["source_families"] == ["yahoo"]


def test_yahoo_yahooquery_yfinance_independent_source_count_is_one() -> None:
    """Test case 4: Yahoo + yahooquery + yfinance => independent_source_count = 1."""
    out, audit = reconcile_option_chains(
        {
            "yahoo": _option_frame("yahoo", bid=1.0, ask=1.1),
            "yahooquery": _option_frame("yahooquery", bid=1.005, ask=1.105),
            "yfinance": _option_frame("yfinance", bid=1.01, ask=1.11),
        },
        freshness={
            "yahoo": "unofficial / may be delayed",
            "yahooquery": "unofficial / may be delayed",
            "yfinance": "unofficial / may be delayed",
        },
    )
    row = out.iloc[0]
    assert row["fabric_source_count"] == 3
    assert row["fabric_independent_source_count"] == 1
    assert audit["independent_source_count"] == 1
    assert audit["source_families"] == ["yahoo"]


# ============================================================================
# CONSENSUS TESTS
# ============================================================================


def test_two_independent_sources_agreeing_consensus_ok() -> None:
    """Test case 5: two independent sources agree => CONSENSUS_OK."""
    out, audit = reconcile_option_chains(
        {
            "tradier": _option_frame("tradier", bid=2.00, ask=2.10),
            "alpaca": _option_frame("alpaca", bid=2.01, ask=2.11),
        },
    )
    row = out.iloc[0]
    assert row["fabric_consensus_pass"] is True, "Consensus passes"
    # Divergence: mids are 2.05 and 2.06, very close
    assert row["fabric_quote_divergence_pct"] < 0.01
    assert audit["consensus_pass"] is True


def test_two_independent_sources_conflicting_data_conflict() -> None:
    """Test case 6: two independent sources materially disagree => DATA_CONFLICT.
    
    Divergence exceeds tolerance, consensus fails.
    """
    out, audit = reconcile_option_chains(
        {
            "tradier": _option_frame("tradier", bid=1.00, ask=1.10),  # mid=1.05
            "alpaca": _option_frame("alpaca", bid=2.00, ask=2.20),   # mid=2.10
        },
        max_quote_divergence_pct=0.08,  # 8% tolerance
    )
    row = out.iloc[0]
    # Divergence = (2.10 - 1.05) / 1.575 ≈ 0.667 = 66.7%, well above 8%
    assert row["fabric_consensus_pass"] is False, "Consensus FAILS due to conflict"
    assert row["fabric_quote_divergence_pct"] > 0.08
    assert audit["consensus_pass"] is False


# ============================================================================
# BID/ASK VALIDITY TESTS
# ============================================================================


def test_missing_bid_not_execution_ready() -> None:
    """Test case 7: missing bid => NOT EXECUTION-READY."""
    gate = assess_execution_quote(
        {
            "source": "licensed feed",
            "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "bid": None,  # MISSING
            "ask": 2.1,
        },
        now=NOW,
    )
    assert gate.execution_ready is False
    assert any("Bid/Ask" in b for b in gate.blockers)


def test_missing_ask_not_execution_ready() -> None:
    """Test case 7b: missing ask => NOT EXECUTION-READY."""
    gate = assess_execution_quote(
        {
            "source": "licensed feed",
            "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "bid": 2.0,
            "ask": None,  # MISSING
        },
        now=NOW,
    )
    assert gate.execution_ready is False


def test_ask_less_than_bid_not_execution_ready() -> None:
    """Test case 8: ask < bid => NOT EXECUTION-READY."""
    gate = assess_execution_quote(
        {
            "source": "licensed feed",
            "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "bid": 2.1,
            "ask": 2.0,  # ASK < BID: INVALID
        },
        now=NOW,
    )
    assert gate.execution_ready is False
    assert any("Bid/Ask" in b for b in gate.blockers)


# ============================================================================
# PROVIDER FAILURE ISOLATION TEST
# ============================================================================


def test_provider_timeout_isolated_others_process() -> None:
    """Test case 9: provider throws exception => provider isolated, others process.
    
    parallel_fetch isolates failures; one timeout should not block other sources.
    """
    from options_radar.data_fabric import parallel_fetch, FabricAttempt

    def good_loader():
        return _option_frame("good")

    def bad_loader():
        raise TimeoutError("Provider hung")

    results = parallel_fetch(
        {
            "good": good_loader,
            "bad": bad_loader,
        },
        operation="get_chain",
        row_counter=lambda x: len(x) if isinstance(x, pd.DataFrame) else 0,
    )
    
    # Should have two results
    assert len(results) == 2
    
    # Find the good and bad results
    good_result = next((r for r in results if r.provider == "good"), None)
    bad_result = next((r for r in results if r.provider == "bad"), None)
    
    assert good_result is not None
    assert good_result.attempt.success is True
    
    assert bad_result is not None
    assert bad_result.attempt.success is False
    assert "TimeoutError" in bad_result.attempt.error


# ============================================================================
# DELAYED SOURCE EXECUTION READINESS TEST
# ============================================================================


def test_delayed_source_label_prevents_execution_ready() -> None:
    """Test case 10: delayed source mislabeled as 'live' => NO EXECUTION-READY.
    
    Text labels alone cannot grant execution authority.
    """
    gate = assess_execution_quote(
        {
            "source": "delayed_feed_but_calling_it_live",
            "freshness_label": "delayed",  # Explicit delayed flag takes precedence
            "data_mode": "delayed",
            "quote_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "bid": 2.0,
            "ask": 2.1,
        },
        now=NOW,
    )
    assert gate.confidence == "RESEARCH"
    assert gate.execution_ready is False
    assert gate.source_mode == "DELAYED_OR_RESEARCH"


# ============================================================================
# FUTURE TIMESTAMP TEST
# ============================================================================


def test_quote_timestamp_future_outside_clock_skew_blocked() -> None:
    """Test case 11: quote_timestamp in future => BLOCKED."""
    future_quote = (NOW + timedelta(seconds=10)).isoformat()
    gate = assess_execution_quote(
        {
            "source": "licensed feed",
            "quote_timestamp": future_quote,
            "bid": 2.0,
            "ask": 2.1,
        },
        now=NOW,
        max_clock_skew_seconds=5.0,
    )
    assert gate.execution_ready is False
    assert any("future" in b.lower() or "skew" in b.lower() for b in gate.blockers)


# ============================================================================
# OCC CONTRACT IDENTITY PRESERVATION TEST
# ============================================================================


def test_occ_contract_symbol_preserved_exact() -> None:
    """Test case 12: OCC contract identity preserved, no synthetic NBBO.
    
    Reconcile should preserve exact contract symbol and never mix bid from one
    provider with ask from another.
    """
    contract = "SPY261219C00450000"
    
    frame_a = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "SPY",
                "expiration": "2026-12-19",
                "strike": 450.0,
                "option_type": "call",
                "bid": 1.00,
                "ask": 1.05,  # Provider A asks
                "volume": 100,
                "open_interest": 200,
                "data_quality": 0.9,
            }
        ]
    )
    
    frame_b = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "SPY",
                "expiration": "2026-12-19",
                "strike": 450.0,
                "option_type": "call",
                "bid": 0.99,  # Provider B bids lower
                "ask": 1.06,
                "volume": 200,
                "open_interest": 300,
                "data_quality": 0.85,
            }
        ]
    )
    
    out, audit = reconcile_option_chains(
        {
            "provider_a": frame_a,
            "provider_b": frame_b,
        },
    )
    
    row = out.iloc[0]
    
    # Contract identity must be preserved exactly
    assert row["contract_symbol"] == contract
    
    # Bid and ask must come from same provider (not synthetic)
    # Both should be either from A (1.00/1.05) or B (0.99/1.06)
    bid = float(row["bid"])
    ask = float(row["ask"])
    
    # Either (A's: 1.00/1.05) or (B's: 0.99/1.06)
    # Not synthetic like (0.99/1.05)
    provider_match = (
        (abs(bid - 1.00) < 0.001 and abs(ask - 1.05) < 0.001) or  # A's pair
        (abs(bid - 0.99) < 0.001 and abs(ask - 1.06) < 0.001)      # B's pair
    )
    assert provider_match, f"Bid/ask must be paired from same provider, got bid={bid}, ask={ask}"
    
    assert bid <= ask, "Bid must not exceed ask"
