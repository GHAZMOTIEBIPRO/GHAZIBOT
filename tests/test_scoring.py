from __future__ import annotations

import pandas as pd

from options_radar.indicators import TechnicalSnapshot
from options_radar.scoring import score_chain
from options_radar.settings import Settings


def test_high_quality_call_passes() -> None:
    chain = pd.DataFrame([{
        "contract_symbol": "XYZ260821C00105000", "symbol": "XYZ",
        "expiration": pd.Timestamp.today().normalize() + pd.Timedelta(days=30),
        "strike": 105.0, "option_type": "call", "bid": 3.0, "ask": 3.2,
        "last": 3.2, "volume": 1800, "open_interest": 500, "iv": 0.38,
        "delta": 0.45, "gamma": 0.04, "theta": -0.05, "vega": 0.12,
        "underlying_price": 103.0, "updated_at": pd.Timestamp.now(tz="UTC"),
        "source": "test", "data_quality": 0.9, "freshness_label": "test",
        "aggressor_proxy": "ask",
    }])
    technical = TechnicalSnapshot(
        "XYZ", 103, 102, 100, 95, 90, 62, 1.2, 0.8, 3, 0.34, 1.8,
        101, 94, "bullish", "breakout", 20, True,
    )
    result = score_chain(chain, technical, "risk_on", Settings(min_score=60, alert_score=70))
    assert len(result) == 1
    assert result.iloc[0]["score"] >= 70
    assert bool(result.iloc[0]["new_setup_candidate"])


def test_filled_greeks_are_labeled_modeled_not_provider() -> None:
    row = {
        "contract_symbol": "XYZ260821C00105000", "symbol": "XYZ",
        "expiration": pd.Timestamp.today().normalize() + pd.Timedelta(days=30),
        "strike": 105.0, "option_type": "call", "bid": 3.0, "ask": 3.2,
        "last": 3.2, "volume": 1800, "open_interest": 500, "iv": 0.38,
        "delta": None, "gamma": None, "theta": None, "vega": None,
        "underlying_price": 103.0, "updated_at": pd.Timestamp.now(tz="UTC"),
        "source": "yahoo/yfinance", "data_quality": 0.5, "freshness_label": "test",
        "aggressor_proxy": "ask",
    }
    provider = {**row, "contract_symbol": "XYZ260821C00110000", "strike": 110.0,
                "delta": 0.35, "gamma": 0.03}
    technical = TechnicalSnapshot(
        "XYZ", 103, 102, 100, 95, 90, 62, 1.2, 0.8, 3, 0.34, 1.8,
        101, 94, "bullish", "breakout", 20, True,
    )
    result = score_chain(pd.DataFrame([row, provider]), technical, "risk_on",
                         Settings(min_score=0, alert_score=70))
    by_strike = {float(r["strike"]): r for _, r in result.iterrows()}
    assert by_strike[105.0]["delta_source"] == "MODELED_BLACK_SCHOLES"
    assert by_strike[105.0]["gamma_source"] == "MODELED_BLACK_SCHOLES"
    assert by_strike[110.0]["delta_source"] == "PROVIDER"
    assert by_strike[110.0]["gamma_source"] == "PROVIDER"
