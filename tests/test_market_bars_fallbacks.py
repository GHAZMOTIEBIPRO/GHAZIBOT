from pathlib import Path

from datetime import datetime, timezone

import pandas as pd

import options_radar.market_bars as bars
from options_radar.market_bars import BarResult
from options_radar.settings import Settings


def _frame():
    index = pd.to_datetime(["2026-10-01T14:30:00Z"])
    return pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000]},
        index=index,
    )


def test_market_bars_falls_from_yahooquery_to_yfinance(monkeypatch):
    settings = Settings(daily_provider_order="yahooquery,yahoo")
    monkeypatch.setattr(
        bars, "_yahooquery",
        lambda *args, **kwargs: BarResult(pd.DataFrame(), "yahoo/yahooquery", "unofficial"),
    )
    monkeypatch.setattr(
        bars, "_yahoo",
        lambda *args, **kwargs: BarResult(_frame(), "yahoo/yfinance", "unofficial"),
    )
    result = bars.fetch_bars(settings, "TEST", interval="1d", period="1mo")
    assert result.source == "yahoo/yfinance"
    assert len(result.frame) == 1


def test_market_bars_accepts_yahooquery_as_same_family_transport(monkeypatch):
    settings = Settings(daily_provider_order="yahooquery,yahoo")
    monkeypatch.setattr(
        bars, "_yahooquery",
        lambda *args, **kwargs: BarResult(_frame(), "yahoo/yahooquery", "unofficial Yahoo fallback"),
    )
    result = bars.fetch_bars(settings, "TEST", interval="1d", period="1mo")
    assert result.source == "yahoo/yahooquery"
    assert "unofficial" in result.freshness.lower()


def test_yahooquery_is_reported_as_same_family_fallback():
    sources = bars.configured_bar_sources(Settings())
    yahooquery = next(row for row in sources if row["name"] == "yahooquery")
    assert yahooquery["configured"] is True
    assert "same source family" in yahooquery["role"]


def test_market_bar_provider_order_is_deduplicated_preserving_order():
    settings = Settings(
        daily_provider_order="tradier,yahooquery,yahooquery,yahoo,tradier"
    )
    assert bars._provider_names(settings, intraday=False) == [
        "tradier",
        "yahooquery",
        "yahoo",
    ]


def test_workflow_defaults_do_not_repeat_yahooquery_transport():
    for path in (
        Path(".github/workflows/options-radar.yml"),
        Path(".github/workflows/classical-direction-radar.yml"),
    ):
        assert "yahooquery,yahooquery" not in path.read_text(encoding="utf-8")
