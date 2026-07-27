from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pandas as pd

from options_radar.phase61_intelligence import _social_score, _symbols_from_text
from options_radar.phase61_overlay import (
    _upgrade_contract_recommendations,
    _upgrade_stock_recommendations,
)
from options_radar.phase61_providers import polygon_option_chain
from options_radar.settings import Settings


def test_symbol_detection_and_social_score_are_bounded() -> None:
    symbols = _symbols_from_text("$AAPL bullish calls and TSLA breakout", {"AAPL", "TSLA", "AMD"})
    assert symbols == {"AAPL", "TSLA"}
    score = _social_score(
        {"mentions": 10, "engagement": 500, "bullish": 8, "bearish": 1},
        {"mentions": 5, "engagement": 200, "bullish": 2, "bearish": 2},
    )
    assert 0 < score <= 25


def test_social_only_cannot_promote_stock_recommendation() -> None:
    payload = {
        "stocks": [
            {
                "symbol": "AAPL",
                "score": 90,
                "new_stock_setup": True,
                "entry_state": "confirmed",
            }
        ],
        "stock_recommendations": [
            {
                "symbol": "AAPL",
                "decision": "مراقبة فقط — يحتاج تأكيد مصدر ثانٍ",
                "confidence": 65,
                "confirmed_sources": ["yahoo"],
            }
        ],
    }
    intelligence = {
        "stocks": {
            "AAPL": {
                "sources": ["X recent search", "Reddit communities"],
                "official_sources": [],
                "market_sources": [],
                "social_score": 25,
            }
        }
    }
    _upgrade_stock_recommendations(payload, intelligence)
    recommendation = payload["stock_recommendations"][0]
    assert "يحتاج تأكيد" in recommendation["decision"]
    assert recommendation["cross_source_confirmed"] is False
    assert recommendation["social_sources"] == ["X recent search", "Reddit communities"]


def test_contract_requires_second_market_or_flow_source() -> None:
    payload = {
        "top_calls": [
            {
                "contract_symbol": "AAPL260918C00200000",
                "symbol": "AAPL",
                "flow_momentum_score": 85,
                "buying_flow_type": "Aggressive Buying",
                "unusual_activity_flag": True,
            }
        ],
        "top_puts": [],
        "contract_recommendations": [
            {
                "contract_symbol": "AAPL260918C00200000",
                "decision": "مراقبة فقط — يحتاج تأكيد مصدر ثانٍ",
                "confidence": 65,
                "confirmed_sources": ["yahoo"],
            }
        ],
    }
    _upgrade_contract_recommendations(payload, {"contracts": {}})
    assert "يحتاج مصدر" in payload["contract_recommendations"][0]["decision"]

    payload["contract_recommendations"][0]["confirmed_sources"] = ["tradier"]
    intelligence = {
        "contracts": {
            "AAPL260918C00200000": {
                "sources": ["Benzinga Option Activity"],
                "market_flow_sources": ["benzinga"],
            }
        }
    }
    _upgrade_contract_recommendations(payload, intelligence)
    assert "دخول مشروط" in payload["contract_recommendations"][0]["decision"]
    assert payload["contract_recommendations"][0]["cross_source_confirmed"] is True


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        expiry = (date.today() + timedelta(days=30)).isoformat()
        return {
            "results": [
                {
                    "details": {
                        "ticker": "O:AAPL260918C00200000",
                        "expiration_date": expiry,
                        "strike_price": 200,
                        "contract_type": "call",
                    },
                    "last_quote": {"bid": 4.9, "ask": 5.0, "sip_timestamp": 1785000000000000000},
                    "last_trade": {"price": 5.0, "sip_timestamp": 1785000000000000000},
                    "day": {"volume": 1200, "close": 5.0},
                    "open_interest": 500,
                    "implied_volatility": 0.35,
                    "greeks": {"delta": 0.5, "gamma": 0.04, "theta": -0.03, "vega": 0.12},
                    "underlying_asset": {"price": 195.0},
                }
            ],
            "next_url": None,
        }


class _Session:
    def get(self, *args, **kwargs):
        return _Response()


def test_polygon_option_chain_is_normalized() -> None:
    settings = replace(Settings(), polygon_api_key="test")
    frame = polygon_option_chain(settings, "AAPL", 14, 60, session=_Session())
    assert not frame.empty
    row = frame.iloc[0]
    assert row["source"] == "polygon_options"
    assert int(row["volume"]) == 1200
    assert int(row["open_interest"]) == 500
    assert pd.notna(row["updated_at"])
