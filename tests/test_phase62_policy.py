from __future__ import annotations

from datetime import datetime, timezone

from options_radar.phase62_policy import (
    _apply_stock_tiers,
    _near_miss_contracts,
    source_class,
)
from options_radar.spx_0dte import evaluate_spx_0dte_snapshot


def test_source_classes_are_domain_aware() -> None:
    assert source_class("Yahoo", "stock") == "stock_quote"
    assert source_class("Yahoo", "option") == "options_quote"
    assert source_class("FINRA Reg SHO", "stock") == "market_context"
    assert source_class("Benzinga Option Activity", "option") == "options_flow"


def test_stock_tier_a_requires_market_and_directional_classes() -> None:
    payload = {
        "stocks": [
            {
                "symbol": "ABC",
                "score": 82,
                "entry_state": "confirmed",
                "new_stock_setup": True,
            }
        ],
        "stock_recommendations": [
            {
                "symbol": "ABC",
                "confirmed_sources": ["Yahoo"],
                "directional_confirmation_sources": ["SEC EDGAR 8-K"],
            }
        ],
    }
    rows = _apply_stock_tiers(payload)
    assert rows[0]["opportunity_tier"] == "A"
    assert set(rows[0]["evidence_classes"]) == {"stock_quote", "official_catalyst"}


def test_finra_context_does_not_create_stock_tier_a() -> None:
    payload = {
        "stocks": [
            {
                "symbol": "ABC",
                "score": 82,
                "entry_state": "confirmed",
                "new_stock_setup": True,
            }
        ],
        "stock_recommendations": [
            {
                "symbol": "ABC",
                "confirmed_sources": ["Yahoo"],
                "supporting_context_sources": ["FINRA Reg SHO"],
            }
        ],
    }
    rows = _apply_stock_tiers(payload)
    assert rows[0]["opportunity_tier"] == "B"
    assert "محفز أو تأكيد اتجاهي مستقل" in rows[0]["missing_confirmations"]


def test_near_miss_contract_is_published_as_tier_b() -> None:
    payload = {
        "rejected": [
            {
                "kind": "option",
                "symbol": "XYZ",
                "contract_symbol": "XYZ260821C00100000",
                "option_type": "call",
                "bid": 2.0,
                "ask": 2.1,
                "last": 2.05,
                "volume": 900,
                "open_interest": 1200,
                "spread_pct": 0.0476,
                "last_trade_age_minutes": 2,
                "flow_momentum_score": 66,
                "source": "Yahoo",
                "rejection_reason": "direction_delta_dte_or_score_filter",
            }
        ]
    }
    rows = _near_miss_contracts(payload, set())
    assert rows[0]["opportunity_tier"] == "B"
    assert "مصدر Flow مستقل" in rows[0]["missing_confirmations"]


def test_invalid_quote_stays_tier_c() -> None:
    payload = {
        "rejected": [
            {
                "kind": "option",
                "symbol": "XYZ",
                "contract_symbol": "XYZ260821C00100000",
                "option_type": "call",
                "bid": 0,
                "ask": 2.1,
                "volume": 900,
                "open_interest": 1200,
                "spread_pct": 1.0,
                "last_trade_age_minutes": 2,
                "flow_momentum_score": 80,
                "source": "Yahoo",
                "rejection_reason": "invalid_bid_ask",
            }
        ]
    }
    rows = _near_miss_contracts(payload, set())
    assert rows[0]["opportunity_tier"] == "C"


def test_spx_0dte_a_tier_requires_quote_and_flow() -> None:
    now = datetime.now(timezone.utc)
    result = evaluate_spx_0dte_snapshot(
        {
            "spot": 6005,
            "orb_high": 6000,
            "orb_low": 5980,
            "vwap": 5998,
            "ema9": 6002,
            "ema21": 5997,
            "vix": 17.5,
            "expected_move": 45,
            "updated_at": now.isoformat(),
            "source_classes": [
                "underlying_intraday",
                "options_quote",
                "options_flow",
            ],
            "candidate_contract": {
                "contract_symbol": "SPXW260728C06010000",
                "bid": 5.00,
                "ask": 5.25,
                "spread_pct": 0.0476,
            },
        },
        now=now,
    )
    assert result["opportunity_tier"] == "A"
    assert result["signal"] == "CALL"
    assert result["automatic_execution"] is False
