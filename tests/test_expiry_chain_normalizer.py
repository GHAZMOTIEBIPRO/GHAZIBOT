from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from options_radar.expiry_chain_normalizer import normalize_expiry_chain
from options_radar.hybrid_fetcher import DataFetcher
from options_radar.settings import Settings


def test_normalizer_restores_dte_spread_and_missing_delta() -> None:
    expiration = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": "AAPL260806C00200000",
                "symbol": "AAPL",
                "expiration": expiration,
                "strike": 200.0,
                "option_type": "call",
                "bid": 4.80,
                "ask": 5.00,
                "last": 4.95,
                "volume": 900,
                "open_interest": 1400,
                "iv": 0.32,
                "delta": np.nan,
                "gamma": np.nan,
                "theta": np.nan,
                "vega": np.nan,
                "underlying_price": 202.0,
                "updated_at": datetime.now(timezone.utc),
                "source": "yahoo/yfinance",
                "freshness_label": "unofficial / may be delayed",
            }
        ]
    )

    normalized = normalize_expiry_chain(frame, DataFetcher(Settings()))

    assert 6 <= int(normalized.iloc[0]["dte"]) <= 7
    assert abs(float(normalized.iloc[0]["spread_pct"]) - 0.04) < 1e-9
    assert 0 < float(normalized.iloc[0]["delta"]) < 1
    assert normalized.iloc[0]["greeks_method"] == "black_scholes_modeled"


def test_expired_contract_keeps_negative_dte_and_no_modeled_delta() -> None:
    expiration = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    frame = pd.DataFrame(
        [
            {
                "contract_symbol": "AAPL260728C00200000",
                "symbol": "AAPL",
                "expiration": expiration,
                "strike": 200.0,
                "option_type": "call",
                "bid": 1.0,
                "ask": 1.1,
                "iv": 0.30,
                "delta": np.nan,
                "underlying_price": 202.0,
                "source": "yahoo/yfinance",
            }
        ]
    )

    normalized = normalize_expiry_chain(frame, DataFetcher(Settings()))

    assert int(normalized.iloc[0]["dte"]) < 0
    assert pd.isna(normalized.iloc[0]["delta"])
