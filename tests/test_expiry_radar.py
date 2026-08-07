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
                "target_3": 225,
                "invalidation": 196,
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


def _identity(
    family: str,
    dte: int,
    expiration: str,
    *,
    method: str = "provider_metadata:provider_expiry_family",
) -> dict:
    return {
        "expiry_family": family,
        "calendar_dte": dte,
        "trading_dte": dte,
        "dte_bucket": expiry_bucket(dte),
        "classification_method": method,
        "classification_confidence": 0.99,
        "expiration_date": expiration,
        "root_symbol": "AAPL",
        "option_root": "AAPL",
        "settlement_type": "PHYSICAL",
        "settlement_time": "PM",
        "exercise_style": "AMERICAN",
        "multiplier": 100,
        "expiry_source": "tradier",
        "is_standard_monthly": family == "STANDARD_MONTHLY",
        "is_weekly": family == "WEEKLY",
        "is_daily": family == "DAILY",
        "is_quarterly": family == "QUARTERLY",
        "is_end_of_month": family == "END_OF_MONTH",
        "is_leaps": family == "LEAPS",
    }


def test_expiry_bucket_is_only_a_holding_horizon() -> None:
    assert expiry_bucket(0) == "0DTE"
    assert expiry_bucket(2) == "1-2_DTE"
    assert expiry_bucket(3) == "3-7_DTE"
    assert expiry_bucket(10) == "8-14_DTE"
    assert expiry_bucket(20) == "15-30_DTE"
    assert expiry_bucket(45) == "31-60_DTE"
    assert expiry_bucket(61) == "60+_DTE"


def test_primary_quote_and_independent_flow_can_reach_tier_a() -> None:
    contract = "AAPL260814C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-14T00:00:00+00:00",
                "dte": 7,
                "option_type": "call",
                "strike": 200,
                "bid": 2.00,
                "ask": 2.10,
                "last": 2.05,
                "volume": 1200,
                "open_interest": 1000,
                "delta": 0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.12,
                "iv": 0.35,
                "underlying_price": 202.0,
                "greeks_method": "provider",
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                "freshness_label": "brokerage feed",
                **_identity("WEEKLY", 7, "2026-08-14"),
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
    assert rows[0]["opportunity_tier"] == "A"
    assert rows[0]["expiry_family"] == "WEEKLY"
    assert rows[0]["primary_or_licensed_quote"] is True
    assert rows[0]["flow_sources"] == ["licensed-flow-test"]
    assert rows[0]["fixed_premium_targets_disabled"] is True
    assert rows[0]["option_expected_response"]["method"] == "DELTA_GAMMA_STATIC_IV"


def test_standard_monthly_with_five_dte_is_not_renamed_weekly() -> None:
    contract = "AAPL260821C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-21T00:00:00+00:00",
                "dte": 5,
                "option_type": "call",
                "strike": 200,
                "bid": 3.00,
                "ask": 3.15,
                "volume": 500,
                "open_interest": 900,
                "delta": 0.48,
                "gamma": 0.02,
                "iv": 0.30,
                "underlying_price": 202.0,
                "greeks_method": "provider",
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                **_identity("STANDARD_MONTHLY", 5, "2026-08-21"),
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    assert len(result["profiles"]["monthly"]["calls"]) == 1
    assert result["profiles"]["weekly"]["calls"] == []
    row = result["profiles"]["monthly"]["calls"][0]
    assert row["expiry_family"] == "STANDARD_MONTHLY"
    assert row["dte"] == 5
    assert row["dte_bucket"] == "3-7_DTE"


def test_weekly_with_twenty_dte_stays_weekly() -> None:
    contract = "AAPL260828C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-28T00:00:00+00:00",
                "dte": 20,
                "option_type": "call",
                "strike": 200,
                "bid": 4.00,
                "ask": 4.20,
                "volume": 600,
                "open_interest": 1200,
                "delta": 0.50,
                "gamma": 0.02,
                "iv": 0.29,
                "underlying_price": 202.0,
                "greeks_method": "provider",
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                **_identity("WEEKLY", 20, "2026-08-28"),
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    row = result["profiles"]["weekly"]["calls"][0]
    assert row["expiry_family"] == "WEEKLY"
    assert row["dte"] == 20
    assert row["dte_bucket"] == "15-30_DTE"


def test_zero_dte_view_does_not_change_weekly_identity() -> None:
    contract = "AAPL260807C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-07T00:00:00+00:00",
                "dte": 0,
                "option_type": "call",
                "strike": 200,
                "bid": 1.00,
                "ask": 1.05,
                "volume": 1000,
                "open_interest": 1200,
                "delta": 0.45,
                "gamma": 0.05,
                "iv": 0.40,
                "underlying_price": 202.0,
                "greeks_method": "provider",
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                **_identity("WEEKLY", 0, "2026-08-07"),
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    daily_row = result["profiles"]["daily"]["calls"][0]
    weekly_row = result["profiles"]["weekly"]["calls"][0]
    assert daily_row["expiry_family"] == "WEEKLY"
    assert weekly_row["expiry_family"] == "WEEKLY"
    assert daily_row["dte_bucket"] == "0DTE"


def test_yahoo_never_creates_tier_a_and_modeled_greeks_are_labeled() -> None:
    contract = "AAPL260814C00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-14T00:00:00+00:00",
                "dte": 7,
                "option_type": "call",
                "strike": 200,
                "bid": 3.00,
                "ask": 3.15,
                "last": 3.10,
                "volume": 2500,
                "open_interest": 3000,
                "delta": 0.45,
                "gamma": 0.03,
                "iv": 0.32,
                "underlying_price": 202.0,
                "greeks_method": "black_scholes_modeled",
                "updated_at": datetime.now(timezone.utc),
                "source": "yahoo/yfinance",
                "freshness_label": "unofficial / may be delayed",
                **_identity("WEEKLY", 7, "2026-08-14", method="calendar_fallback"),
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    row = result["profiles"]["weekly"]["calls"][0]
    assert row["opportunity_tier"] != "A"
    assert row["primary_or_licensed_quote"] is False
    assert row["greeks_source"] == "MODELED"
    assert row["option_expected_response"]["available"] is False
    assert "مصدر Quote مرخص/أساسي غير متاح" in row["missing_confirmations"]
    assert "Greeks MODELED وليست Provider Greeks" in row["missing_confirmations"]


def test_opposite_contract_side_is_not_published() -> None:
    contract = "AAPL260814P00200000"
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": contract,
                "symbol": "AAPL",
                "expiration": "2026-08-14T00:00:00+00:00",
                "dte": 7,
                "option_type": "put",
                "strike": 200,
                "bid": 2.00,
                "ask": 2.10,
                "volume": 1000,
                "open_interest": 1000,
                "delta": -0.45,
                "gamma": 0.03,
                "underlying_price": 202.0,
                "greeks_method": "provider",
                "updated_at": datetime.now(timezone.utc),
                "source": "tradier",
                **_identity("WEEKLY", 7, "2026-08-14"),
            }
        ]
    )
    result = build_expiry_radar(
        _payload(contract),
        fetcher=_Fetcher(frame),
        max_symbols=1,
        top_per_side=5,
    )
    assert result["profiles"]["weekly"]["puts"] == []
