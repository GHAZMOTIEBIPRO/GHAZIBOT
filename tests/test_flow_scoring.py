from __future__ import annotations

import pandas as pd

from options_radar.flow_scoring import score_chain_with_ask_spread
from options_radar.indicators import TechnicalSnapshot
from options_radar.settings import Settings


def test_exact_ask_based_fifteen_percent_spread_passes_scoring(tmp_path):
    technical = TechnicalSnapshot(
        symbol="AAPL",
        close=200.0,
        ema9=198.0,
        ema21=195.0,
        ema50=190.0,
        ema200=170.0,
        rsi14=60.0,
        macd=2.0,
        macd_signal=1.0,
        atr14=4.0,
        realized_vol20=0.30,
        relative_volume20=2.0,
        resistance20=199.0,
        support20=185.0,
        direction="bullish",
        catalyst="test",
        catalyst_score=20.0,
        breakout=True,
    )
    chain = pd.DataFrame(
        [
            {
                "contract_symbol": "AAPL260828C00200000",
                "symbol": "AAPL",
                "expiration": pd.Timestamp.today().normalize()
                + pd.Timedelta(days=30),
                "strike": 200.0,
                "option_type": "call",
                "bid": 0.85,
                "ask": 1.00,
                "last": 1.00,
                "volume": 500,
                "open_interest": 200,
                "iv": 0.30,
                "delta": 0.50,
                "gamma": 0.03,
                "theta": -0.02,
                "vega": 0.05,
                "underlying_price": 200.0,
                "updated_at": pd.Timestamp.now(tz="UTC"),
                "source": "test",
                "data_quality": 0.95,
                "freshness_label": "test",
                "aggressor_proxy": "ask",
                "unusual_activity_flag": True,
                "flow_momentum_score": 90.0,
            }
        ]
    )
    settings = Settings(
        database_path=tmp_path / "state.json",
        min_option_volume=1,
        min_open_interest=1,
        min_score=0,
        max_spread_pct=0.15,
    )
    result = score_chain_with_ask_spread(
        chain, technical, "risk_on", settings
    )
    assert len(result) == 1
    assert round(float(result.iloc[0]["spread_pct"]), 6) == 0.15
