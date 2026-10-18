from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts.build_index_context import (
    SYMBOLS, analyze, atr14, clean_bars, completed_daily,
    hourly_from_quarters, last_finished_intraday, make_report,
    previous_period_range, technical,
)

NY = ZoneInfo("America/New_York")


def daily_bars() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-10-16", periods=110, tz=NY)
    closing = [400 + i * 0.6 for i in range(len(dates))]
    return pd.DataFrame({
        "Open": [x-0.2 for x in closing],
        "High": [x+1.3 for x in closing],
        "Low": [x-1.4 for x in closing],
        "Close": closing,
        "Volume": [1000] * len(dates),
    }, index=dates)


def intraday_bars() -> pd.DataFrame:
    dates = pd.date_range("2026-10-16 09:30", periods=26, freq="15min", tz=NY)
    prices = [460 + i*0.12 for i in range(26)]
    return pd.DataFrame({
        "Open": prices,
        "High": [x+0.2 for x in prices],
        "Low": [x-0.2 for x in prices],
        "Close": prices,
        "Volume": [500] * 26,
    }, index=dates)


def test_intraday_does_not_use_unfinished_candle() -> None:
    now = datetime(2026, 10, 16, 15, 46, tzinfo=NY)
    done = last_finished_intraday(clean_bars(intraday_bars(), intraday=True), now)
    assert done.index[-1].strftime("%H:%M") == "15:30"
    assert done.index[-1] + pd.Timedelta(minutes=15) <= now


def test_completed_five_min_candles_are_distinct_from_incomplete_candles() -> None:
    from scripts.build_index_context import last_finished_five_min
    now = datetime(2026, 10, 16, 15, 46, tzinfo=NY)
    stamps = pd.date_range("2026-10-16 09:30", periods=80, freq="5min", tz=NY)
    prices = [440 + i*0.11 for i in range(80)]
    bars = pd.DataFrame({
        "Open":prices, "High":[x+0.3 for x in prices],
        "Low":[x-0.3 for x in prices],"Close":prices,
        "Volume":[1000 for _ in prices],
    },index=stamps)
    complete = last_finished_five_min(clean_bars(bars, intraday=True), now)
    assert complete.index[-1].strftime("%H:%M") == "15:40"
    assert all((complete.index + pd.Timedelta(minutes=5)) <= pd.Timestamp(now))
    result = analyze("SPX", daily_bars(), intraday_bars(), now=now, five_min_raw=bars)
    assert result["current_m5_confirmed"] is True
    assert result["m5"]["ema_fast"] is not None
    assert result["m5"]["bias"] != "STALE"
    stale = analyze("SPX", daily_bars(), intraday_bars(),
                    now=datetime(2026,10,18,10,tzinfo=NY), five_min_raw=bars)
    assert stale["current_m5_confirmed"] is False
    assert stale["m5"]["bias"] == "STALE"


def test_daily_bar_not_promoted_until_after_close_buffer() -> None:
    frame = clean_bars(daily_bars(), intraday=False)
    before = completed_daily(frame, datetime(2026, 10, 16, 15, 46, tzinfo=NY))
    after = completed_daily(frame, datetime(2026, 10, 16, 16, 40, tzinfo=NY))
    assert before.index[-1].date().isoformat() == "2026-10-15"
    assert after.index[-1].date().isoformat() == "2026-10-16"


def test_weekly_monthly_levels_exclude_current_period() -> None:
    frame = clean_bars(daily_bars(), intraday=False)
    now = datetime(2026, 10, 16, 15, 46, tzinfo=NY)
    completed = completed_daily(frame, now)
    w = previous_period_range(completed, now, kind="week")
    m = previous_period_range(completed, now, kind="month")
    assert w["period"] != "2026-W42"
    assert m["period"] == "2026-09"
    assert w["high"] is not None and w["low"] is not None
    assert m["high"] is not None and m["low"] is not None


def test_index_vs_etf_proxy_no_vwap_for_index() -> None:
    now = datetime(2026, 10, 16, 15, 46, tzinfo=NY)
    spx = analyze("SPX", daily_bars(), intraday_bars(), now=now)
    spy = analyze("SPY", daily_bars(), intraday_bars(), now=now)
    assert spx["vwap_today"] is None
    assert spy["vwap_today"] is not None
    assert spx["current_intraday_bar_confirmed"] is True
    assert spx["last_completed_session_date"] == "2026-10-15"
    assert spx["quote_execution_eligible"] is False
    assert spx["research_only"] is True
    assert spx["daily"]["ema_fast"] is not None
    assert spx["daily"]["rsi14"] is not None
    assert spx["last_finished_intraday_age_minutes"] >= 15


def test_stale_offsession_intraday_never_produces_fresh_bias() -> None:
    now = datetime(2026, 10, 18, 8, 30, tzinfo=NY)
    report = analyze("QQQ", daily_bars(), intraday_bars(), now=now)
    assert report["current_intraday_bar_confirmed"] is False
    assert report["m15"]["bias"] == "STALE"
    assert report["h1"]["bias"] == "STALE"
    assert report["vwap_today"] is None
    assert report["last_finished_intraday_close"] is None


def test_empty_provider_does_not_invent_confirmed_symbols() -> None:
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="No validated"):
        make_report({}, {}, now=now)


def test_report_keeps_research_only_authority() -> None:
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    report = make_report({"SPX": daily_bars()}, {}, now=now)
    assert report["coverage"]["daily_validated"] == 1
    assert report["coverage"]["intraday_current"] == 0
    assert report["data_role"] == "RESEARCH_ONLY_NOT_LICENSED_EXECUTION"
    assert report["index_options_signal_authority"] is False
    assert len(report["symbols"]) == len(SYMBOLS)
    assert report["symbols"]["NDX"]["daily"]["bias"] == "UNAVAILABLE"
    assert report["symbols"]["SPX"]["m15"]["bias"] == "STALE"


def test_hourly_cannot_count_partial_15min_chunks() -> None:
    bars = last_finished_intraday(intraday_bars(), datetime(2026, 10, 16, 15, 46, tzinfo=NY))
    hour = hourly_from_quarters(bars)
    assert all(pd.notna(hour["Close"]))
    assert len(hour) <= 6
    assert technical(hour, fast=9, slow=21)["bias"] == "INSUFFICIENT"


def test_fallback_rejects_naive_intraday_times_and_invalid_ohlc() -> None:
    frame = intraday_bars()
    frame.index = frame.index.tz_localize(None)
    assert clean_bars(frame, intraday=True).empty
    valid = daily_bars()
    valid.iloc[0, valid.columns.get_loc("High")] = 1
    assert len(clean_bars(valid, intraday=False)) == len(valid) - 1


def test_site_includes_actual_index_engine_and_source_warning() -> None:
    html = Path("public/index.html").read_text(encoding="utf-8")
    js = Path("public/index-radar.js").read_text(encoding="utf-8")
    assert 'data-tab="indices"' in html
    assert 'id="tab-indices"' in html
    assert "index-radar.js" in html and "index-radar.css" in html
    assert "SPX" in html and "NDX" in html and "RUT" in html
    assert "ghazi.index_research.v1" in js
    assert "index_options_signal_authority===false" in js
    assert "RESEARCH_ONLY_NOT_LICENSED_EXECUTION" in js
    assert "Promise.allSettled" in js
    assert "textContent" in js


def test_homepage_indicators_and_news_are_visible_without_opening_tabs() -> None:
    from pathlib import Path
    html=Path("public/index.html").read_text(encoding="utf-8")
    begin=html.index('id="indices-overview"')
    tabs=html.index('<nav class="tabs"')
    assert begin < tabs
    assert html.index('id="catalyst-overview"') < tabs
    assert 'id="indices-overview-grid"' in html
    assert 'id="catalyst-upside-grid"' in html
    assert "catalyst-overview.js" in html and "catalyst-overview.css" in html
    assert Path("public/data/index_radar.json").exists()
    import json
    data=json.loads(Path("public/data/index_radar.json").read_text(encoding="utf-8"))
    assert data["schema"] == "ghazi.index_research.v1"
    assert data["coverage"]["daily_validated"] > 0
    assert data["symbols"]["SPX"]["last_completed_session_date"] is not None
    assert data["index_options_signal_authority"] is False
