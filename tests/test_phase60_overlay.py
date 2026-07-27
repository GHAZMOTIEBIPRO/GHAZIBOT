from __future__ import annotations

from options_radar.phase60_overlay import apply_phase60_overlay
from options_radar.phase60_sources import _consensus_metadata

import pandas as pd


def _payload() -> dict:
    return {
        "schema_version": 5,
        "phase": "5.1",
        "summary": {},
        "stocks": [
            {
                "symbol": "AAPL",
                "score": 82,
                "rating": "A",
                "setup_side": "call",
                "entry_state": "confirmed",
                "new_stock_setup": True,
                "catalyst_confidence": 0.9,
                "entry_low": 200,
                "entry_high": 202,
                "target_1": 208,
                "target_2": 215,
                "invalidation": 196,
                "best_option": {"contract_symbol": "SHOULD_BE_REMOVED"},
            }
        ],
        "top_calls": [
            {
                "contract_symbol": "AAPL260116C00200000",
                "symbol": "AAPL",
                "option_type": "call",
                "score": 80,
                "flow_momentum_score": 78,
                "buying_flow_type": "Aggressive Buying",
                "unusual_activity_flag": True,
            }
        ],
        "top_puts": [],
        "provider_audit": {},
    }


def test_single_source_is_watch_only_and_stock_contracts_are_separate(monkeypatch):
    audit = {
        "stocks": {
            "AAPL": {
                "metadata": {
                    "successful_sources": ["yahoo"],
                    "source_count": 1,
                    "cross_source_confirmed": False,
                }
            }
        },
        "options": {
            "AAPL": {
                "metadata": {
                    "successful_sources": ["yahoo"],
                    "source_count": 1,
                    "cross_source_confirmed": False,
                }
            }
        },
    }
    monkeypatch.setattr("options_radar.phase60_overlay._read_json", lambda _path: audit)
    result = apply_phase60_overlay(_payload())

    assert result["schema_version"] == 6
    assert result["phase"] == "6.0"
    assert "best_option" not in result["stocks"][0]
    assert "مراقبة فقط" in result["stock_recommendations"][0]["decision"]
    assert result["stock_recommendations"][0]["confidence"] <= 65
    assert "مراقبة فقط" in result["contract_recommendations"][0]["decision"]


def test_two_independent_sources_allow_conditional_recommendations(monkeypatch):
    audit = {
        "stocks": {
            "AAPL": {
                "metadata": {
                    "successful_sources": ["tiingo", "yahoo"],
                    "source_count": 2,
                    "cross_source_confirmed": True,
                    "latest_close_dispersion_pct": 0.2,
                }
            }
        },
        "options": {
            "AAPL": {
                "metadata": {
                    "successful_sources": ["tradier", "yahoo"],
                    "source_count": 2,
                    "cross_source_confirmed": True,
                }
            }
        },
    }
    monkeypatch.setattr("options_radar.phase60_overlay._read_json", lambda _path: audit)
    result = apply_phase60_overlay(_payload())

    assert "دخول مشروط" in result["stock_recommendations"][0]["decision"]
    assert "دخول مشروط" in result["contract_recommendations"][0]["decision"]
    assert result["recommendation_policy"]["minimum_sources_for_strong_recommendation"] == 2


def test_stock_consensus_detects_matching_and_divergent_prices():
    index = pd.date_range("2026-07-20", periods=2, tz="UTC")
    close_a = pd.DataFrame({"Close": [100, 101]}, index=index)
    close_b = pd.DataFrame({"Close": [100, 101.5]}, index=index)
    matching = _consensus_metadata(
        [("tiingo", close_a, "fresh"), ("yahoo", close_b, "delayed")]
    )
    assert matching["source_count"] == 2
    assert matching["cross_source_confirmed"] is True

    close_c = pd.DataFrame({"Close": [100, 110]}, index=index)
    divergent = _consensus_metadata(
        [("tiingo", close_a, "fresh"), ("yahoo", close_c, "delayed")]
    )
    assert divergent["cross_source_confirmed"] is False
