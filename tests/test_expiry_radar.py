from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from options_radar.expiry_radar import build_expiry_radar, expiry_bucket


@dataclass
class _Result:
    data: pd.DataFrame

    def audit_dict(self):
        return {
            "source": "test",
            "freshness": "test",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "attempts": [],
            "metadata": {},
        }


class _Fetcher:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def fetch_option_chain(self, *args, **kwargs):
        return _Result(self.frame.copy())


def _payload(contract: str) -> dict:
    return {
        "stocks": [
            {
                "symbol": "AAPL",
                "score": 84,
                "rating": "A",
                "setup_side": "CALL",
                "technical_direction": "bullish",
                "entry_low": 200,
                "entry_high": 202,
                "target_1": 210,
                "target_2": 218,
            }
        ],
        "stock_recommendations": [
            {
                "symbol": "AAPL",
                "opportunity_tier": "B",
                "decision": "B — فرصة قيد التأكيد",
            }
        ],
        "intelligence": {
            "contracts": {
                contract: {
                    "market_flow_sources": ["licensed-flow-test"],
                }
            }
        },
    }


def test_expiry_bucket_boundaries() -> None:
    assert expiry_bucket(0) == "daily"
    assert expiry_bucket(2) == "daily"
    assert expiry_bucket(3) == "weekly"
    assert expiry_bucket(10) == "weekly"
    assert expiry_bucket(11) == "monthly"
    assert expiry_bucket(45) == "monthly"
    assert expiry_bucket(46) is None


def test_primary_quote_and_independent_flow_can_reach_tier_a() -> None:
    contract = "AAPL260731C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-07-31T00:00:00+00:00",
                "dte": 1,
                "option_type": "call",
                "bid": 2.00,
                "ask": 2.10,
                "last": 2.05,
                "volume": 1200,
                "open_interest": 1000,
                "delta": 0.45,
                "iv": 0.35,
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                "freshness_label": "brokerage feed",
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    rows = result["profiles"]["daily"]["calls"]
    assert len(rows) == 1
    assert rows[0]["opportunity_tier"] == "A"
    assert rows[0]["primary_or_licensed_quote"] is True
    assert rows[0]["flow_sources"] == ["licensed-flow-test"]


def test_yahoo_never_creates_tier_a() -> None:
    contract = "AAPL260814C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-14T00:00:00+00:00",
                "dte": 8,
                "option_type": "call",
                "bid": 3.00,
                "ask": 3.15,
                "last": 3.10,
                "volume": 2500,
                "open_interest": 3000,
                "delta": 0.45,
                "iv": 0.32,
                "updated_at": datetime.now(timezone.utc),
                "source": "yahoo/yfinance",
                "freshness_label": "unofficial / may be delayed",
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    rows = result["profiles"]["weekly"]["calls"]
    assert len(rows) == 1
    assert rows[0]["opportunity_tier"] != "A"
    assert rows[0]["primary_or_licensed_quote"] is False
    assert "مصدر OPRA/مرخص غير متاح" in rows[0]["missing_confirmations"]


def test_opposite_contract_side_is_not_published() -> None:
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": "AAPL260814P00200000",
                "symbol": "AAPL",
                "expiration": "2026-08-14T00:00:00+00:00",
                "dte": 8,
                "option_type": "put",
                "bid": 2.00,
                "ask": 2.10,
                "volume": 1000,
                "open_interest": 1000,
                "delta": -0.45,
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
            }
        ]
    )
    result = build_expiry_radar(
        _payload("AAPL260814P00200000"),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    assert result["profiles"]["weekly"]["puts"] == []
