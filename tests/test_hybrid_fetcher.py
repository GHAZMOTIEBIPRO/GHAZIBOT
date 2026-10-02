from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from options_radar.hybrid_fetcher import DataFetcher
from options_radar.settings import Settings


def _occ(root: str, days: int, side: str = "C", strike: int = 100_000) -> str:
    expiry = (date.today() + timedelta(days=days)).strftime("%y%m%d")
    return f"{root}{expiry}{side}{strike:08d}"


def test_quality_guards_use_ask_denominator_and_strict_ranges():
    fetcher = DataFetcher(Settings())
    frame = pd.DataFrame([
        {
            "contract_symbol": _occ("AAPL", 30),
            "bid": 1.70,
            "ask": 2.00,
            "delta": 0.45,
            "dte": 30,
        },
        {
            "contract_symbol": _occ("AAPL", 30, strike=105_000),
            "bid": 1.69,
            "ask": 2.00,
            "delta": 0.45,
            "dte": 30,
        },
        {
            "contract_symbol": _occ("AAPL", 30, strike=110_000),
            "bid": 1.80,
            "ask": 2.00,
            "delta": 0.20,
            "dte": 30,
        },
    ])
    accepted, rejected = fetcher.apply_option_quality_guards(frame, "AAPL")
    assert len(accepted) == 1
    assert accepted.iloc[0]["spread_pct"] == 0.15
    assert set(rejected["rejection_reason"]) == {
        "spread_above_15pct",
        "delta_outside_030_060",
    }


def test_black_scholes_put_delta_is_negative():
    greek = DataFetcher.black_scholes_greeks(
        spot=100, strike=100, years=30 / 365, rate=0.04, volatility=0.30, side="put"
    )
    assert -0.60 < greek["delta"] < -0.30
    assert greek["gamma"] > 0
    assert greek["vega"] > 0


def test_yahooquery_fallback_can_precede_yfinance_without_breaking(monkeypatch):
    settings = Settings(stock_provider_order="yahooquery,yahoo")
    fetcher = DataFetcher(settings)
    index = pd.to_datetime(["2026-10-01T14:30:00Z"])
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=index,
    )
    monkeypatch.setattr(fetcher, "_yahooquery_bars", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(fetcher, "_yahoo_bars", lambda *args, **kwargs: frame)
    result = fetcher.fetch_stock_bars("TEST", providers=["yahooquery", "yahoo"])
    assert result.source == "yahoo"
    assert len(result.attempts) == 2
    assert result.attempts[0].provider == "yahooquery"
    assert result.attempts[0].success is False
    assert result.attempts[1].success is True


def test_yahooquery_can_serve_as_free_same_family_transport(monkeypatch):
    settings = Settings(stock_provider_order="yahooquery,yahoo")
    fetcher = DataFetcher(settings)
    index = pd.to_datetime(["2026-10-01T14:30:00Z"])
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=index,
    )
    monkeypatch.setattr(fetcher, "_yahooquery_bars", lambda *args, **kwargs: frame)
    result = fetcher.fetch_stock_bars("TEST", providers=["yahooquery", "yahoo"])
    assert result.source == "yahooquery"
    assert "Yahoo fallback" in result.freshness
