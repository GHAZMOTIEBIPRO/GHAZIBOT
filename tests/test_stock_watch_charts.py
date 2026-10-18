"""Offline tests for truly completed free stock-watch OHLC."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts.build_stock_watch_charts import (
    FIVE_MIN, SMALL_WATCH, WATCH, collect, pack_symbol,
)

NY=ZoneInfo("America/New_York")
NOW=datetime(2026,10,16,15,46,tzinfo=NY)


def candles(interval):
    if interval=="1d":
        stamps=pd.bdate_range(end="2026-10-16",periods=85,tz=NY)
    elif interval=="5m":
        stamps=pd.date_range("2026-10-16 09:30",periods=80,freq="5min",tz=NY)
    else:
        stamps=pd.date_range("2026-10-16 09:30",periods=28,freq="15min",tz=NY)
    values=[11+.08*i for i in range(len(stamps))]
    return pd.DataFrame({"Open":values,"High":[v+.25 for v in values],
                         "Low":[v-.25 for v in values],"Close":values,
                         "Volume":[120]*len(stamps)},index=stamps)


def test_true_closed_candles_for_small_cap_watch():
    out=pack_symbol("RGC",candles("1d"),candles("15m"),candles("5m"),now=NOW)
    assert out["category"]=="VOLATILE_GROWTH_WATCH"
    assert out["market_cap_verified"] is False
    assert out["intervals"]["1d"]["bars"][-1]["time"]=="2026-10-15"
    assert out["intervals"]["15m"]["bars"][-1]["time"]==int(
        pd.Timestamp("2026-10-16 15:30",tz=NY).timestamp())
    assert out["intervals"]["5m"]["bars"][-1]["time"]==int(
        pd.Timestamp("2026-10-16 15:40",tz=NY).timestamp())
    assert out["intervals"]["5m"]["technical"]["ema_fast"] is not None
    assert out["options_execution_grade"] is False


def test_weekend_history_not_promoted_to_current_and_no_faked_5m():
    weekend=datetime(2026,10,18,10,tzinfo=NY)
    out=pack_symbol("BNAI",candles("1d"),candles("15m"),candles("5m"),now=weekend)
    assert out["intervals"]["1d"]["bars"][-1]["time"]=="2026-10-16"
    assert out["intervals"]["5m"]["current_session_confirmed"] is False
    assert out["intervals"]["15m"]["current_session_confirmed"] is False
    large=pack_symbol("AAPL",candles("1d"),candles("15m"),None,now=weekend)
    assert "5m" not in large["intervals"]  # No source candles means no invented frame.
    assert large["market_cap_verified"] is False


class Ticker:
    def __init__(self,symbol):
        self.symbol=symbol
    def history(self,*,period,interval,auto_adjust,prepost):
        assert auto_adjust is False and prepost is False
        if self.symbol=="BNAI":
            return pd.DataFrame()
        return candles(interval)


def test_provider_failures_are_explicit_and_no_live_authority():
    provider=SimpleNamespace(Ticker=Ticker)
    out=collect(now=NOW,provider=provider,delay=lambda _:None)
    assert out["schema"]=="ghazi.stock_charts.v1"
    assert out["coverage"]["requested"]==len(WATCH)
    assert out["coverage"]["with_valid_charts"]==len(WATCH)-1
    assert out["coverage"]["with_5m"]==len(FIVE_MIN)-1
    assert "BNAI_1d" in out["coverage"]["errors"]
    assert out["quote_execution_eligible"] is False
    assert out["provider_source_family"]=="yahoo"
    assert set(SMALL_WATCH).issubset(set(WATCH))
    assert len(out["symbols"]["RGC"]["intervals"]["1d"]["bars"])<=110
    assert "5m" in out["symbols"]["AAPL"]["intervals"]
    assert FIVE_MIN == frozenset(WATCH)


def test_absent_candles_never_become_zero_or_live_prices():
    assert pack_symbol("RGC",None,None,None,now=NOW) is None
    assert pack_symbol("RGC",candles("1d"),None,None,now=NOW)["intervals"].keys()=={"1d"}
    with pytest.raises(ValueError):
        collect(now=datetime(2026,10,18,12),provider=SimpleNamespace(Ticker=Ticker))


def test_automatic_refresh_owns_one_dedicated_state_path():
    from pathlib import Path
    text=Path(".github/workflows/stock-watch-charts.yml").read_text(encoding="utf-8")
    assert 'workflows: ["GHAZI RADAR Market Index Research"]' in text
    assert "runtime/public/data/stock_watch_charts.json" in text
    assert "runtime/public/data/index_charts.json" not in text
    assert "cancel-in-progress: false" in text
    page=Path("public/index.html").read_text(encoding="utf-8")
    js=Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert 'id="terminal-gamma-metrics"' in page
    assert 'id="terminal-stock-chart-health"' in page
    assert "ghazi.stock_charts.v1" in js
    assert "free_gex_validation.json" in js
    assert "terminal-chart-scenario" in js
