"""Causal research compression/volume confluence and honest historical replay."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from options_radar.stock_watch_confluence import price_confluence_shadow
from scripts.build_stock_watch_charts import pack_symbol

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 16, 15, 46, tzinfo=NY)


def history(rows=100, breakout=True):
    days = pd.bdate_range(end="2026-10-15", periods=rows, tz=NY)
    x = np.arange(rows)
    close = 100 + 3 * np.sin(x / 2.5)
    close[-12:] = 100 + .03 * np.sin(x[-12:] / 2.5)
    if breakout:
        close[-1] = 108.0
    opening = close - .04
    high = np.maximum(opening, close) + .1
    low = np.minimum(opening, close) - .1
    volumes = np.full(rows, 1000.0)
    if breakout:
        volumes[-1] = 4000.0
    return pd.DataFrame(
        {"Open": opening, "High": high, "Low": low,
         "Close": close, "Volume": volumes}, index=days,
    )


def test_bollinger_narrowing_plus_rvol_and_prior_breakout_is_research_only():
    out = price_confluence_shadow(history())
    assert out["status"] == "RESEARCH_ONLY"
    assert out["stage"] == "BREAKOUT_AFTER_COMPRESSION"
    assert out["breakout_close_above_prior_high"] is True
    assert out["compression_within_prior_5_sessions"] is True
    assert out["volume_confirmation"] is True
    assert out["rvol_daily"] >= 1.5
    assert out["source_last_daily_bar"] == "2026-10-15"
    assert out["live_decision_authority"] is False
    assert out["options_execution_eligible"] is False
    assert out["independent_price_confirmation"] is False
    assert out["official_catalyst_verified"] is False
    assert out["price_probability"] is None
    assert out["historical_replay"]["win_probability"] is None


def test_no_volume_no_confirmation_even_with_breakout():
    frame = history()
    frame.loc[frame.index[-1], "Volume"] = 1000
    out = price_confluence_shadow(frame)
    assert out["stage"] != "BREAKOUT_AFTER_COMPRESSION"
    assert out["volume_confirmation"] is False


def test_not_a_price_prediction_without_breakout():
    out = price_confluence_shadow(history(breakout=False))
    assert out["stage"] in ("COMPRESSION_WATCH", "NO_PATTERN")
    assert out["breakout_after_compression"] is False


def test_a_future_surge_cannot_change_prior_signal():
    frame = history(105)
    prefix = frame.iloc[:-5].copy()
    before = price_confluence_shadow(prefix)
    future = frame.copy()
    future.loc[future.index[-5:], ["Open", "High", "Low", "Close"]] *= 3
    after = price_confluence_shadow(future.iloc[:-5])
    for key in ("stage", "prior_20_high", "prior_20_low", "rvol_daily",
                "breakout_after_compression", "historical_replay"):
        assert before[key] == after[key]
    assert before["historical_replay"]["lookahead_safe"] is True
    assert before["historical_replay"]["measurement"] == (
        "forward five completed daily sessions after signal close"
    )


def test_invalid_or_insufficient_history_never_creates_signal():
    for frame in (
        None, pd.DataFrame(), history(30),
        history().iloc[::-1],
        pd.concat([history(), history().iloc[[-1]]]),
        history().assign(High=0),
        history().assign(Volume=-1),
    ):
        result = price_confluence_shadow(frame)
        assert result["status"] == "UNAVAILABLE"
        assert result["live_decision_authority"] is False
        assert result["historical_replay"]["matured_events"] == 0


def test_chart_builder_publishes_causal_research_under_same_yahoo_source():
    item = pack_symbol("AAPL", history(), None, None, now=NOW)
    assert item is not None
    assert item["price_confluence"]["stage"] == "BREAKOUT_AFTER_COMPRESSION"
    assert item["price_confluence"]["source_family"] == "yahoo"
    assert item["news_attention"] is None
    assert item["options_execution_grade"] is False
    assert item["market_cap_verified"] is False


def test_browser_card_declares_replay_not_validated_win_probability():
    source = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert "price_confluence" in source
    assert "replay.matured_events" in source
    assert "ليست نسبة نجاح" in source
    assert "NEWS_SEARCH_ATTENTION_ONLY" in source
