"""Offline tests for truly completed free stock-watch OHLC."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts.build_stock_watch_charts import (
    FIVE_MIN,
    SMALL_WATCH,
    WATCH,
    collect,
    pack_symbol,
    session_vwap_shadow,
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


def test_collect_fills_the_liquidity_map_from_the_same_completed_bars():
    from scripts.build_stock_watch_charts import liquidity_report
    liquidity={}
    out=collect(now=NOW,provider=SimpleNamespace(Ticker=Ticker),delay=lambda _:None,
                liquidity_out=liquidity)
    assert set(liquidity)==set(out["symbols"])  # BNAI (no data) has no row either
    rgc=liquidity["RGC"]
    # One 15m session only: no prior sessions, so RVOL is withheld, not invented.
    assert rgc["status"]=="OK" and rgc["volume"] is None
    assert rgc["profile_session"]["method"]=="OHLCV_UNIFORM_RANGE_ESTIMATE"
    assert any("دفتر الأوامر" in line for line in rgc["reading_ar"])
    report=liquidity_report(liquidity,now=NOW)
    assert report["schema"]=="ghazi.liquidity_map.v1" and report["order_book_available"] is False
    assert report["inference_only"] is True and report["execution_authority"] is False


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


def test_stale_yahoo_success_cannot_masquerade_as_fresh_stock_coverage():
    # Even a clean HTTP response with valid OHLC is unusable as a new scan
    # if the latest candle is weeks old. Market holidays/weekends remain okay.
    stale_now=NOW+timedelta(days=18)
    assert pack_symbol("RGC",candles("1d"),candles("15m"),
                       candles("5m"),now=stale_now) is None
    with pytest.raises(ValueError,match="No independently valid watched stock candles"):
        collect(now=stale_now,provider=SimpleNamespace(Ticker=Ticker),
                delay=lambda _:None)
    recent=pack_symbol("RGC",candles("1d"),candles("15m"),
                       candles("5m"),now=NOW+timedelta(days=3))
    assert recent is not None
    assert recent["intervals"]["1d"]["source_recency_verified"] is True
    assert recent["options_execution_grade"] is False


def test_vwap_uses_only_completed_intraday_ohlcv_from_source():
    day=candles("15m")
    data=pack_symbol("RGC",candles("1d"),day,candles("5m"),now=NOW)
    result=data["intervals"]["15m"]["session_vwap"]
    assert result["available"] is True
    assert result["research_only"] is True
    assert result["options_execution_eligible"] is False
    assert result["source_family"] == "yahoo"
    assert result["value"] > 0
    assert result["source_last_bar_start"] == data["intervals"]["15m"]["provider_bar_start_or_date"]
    assert result["session_date"] == "2026-10-16"
    assert result["completed_bars"] >= 2


def test_vwap_missing_or_zero_source_volume_is_unavailable_not_zero_price():
    day=candles("15m")
    day["Volume"]=0
    result=session_vwap_shadow(day)
    assert result["available"] is False
    assert result["value"] is None
    assert result["options_execution_eligible"] is False
    assert session_vwap_shadow(None)["available"] is False
    assert session_vwap_shadow(pd.DataFrame())["value"] is None


def test_no_daily_vwap_and_frontend_uses_exact_source_bar_identity():
    data=pack_symbol("RGC",candles("1d"),candles("15m"),candles("5m"),now=NOW)
    assert "session_vwap" not in data["intervals"]["1d"]
    from pathlib import Path
    js=Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert 'session_vwap' in js
    assert 'source_last_bar_start===frame?.provider_bar_start_or_date' in js
    assert 'VWAP جلسة' in js


def test_oversized_report_trims_history_then_bars_but_never_fresh_symbols():
    from scripts.build_stock_watch_charts import fit_size_budget

    def bars(n):
        return [{"time": i, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5} for i in range(n)]

    def item():
        return {"intervals": {u: {"bars": bars(110)} for u in ("1d", "15m", "1h", "5m")}}

    report = {"symbols": {"FRESH1": item(), "FRESH2": item(), "OLD1": item(), "OLD2": item()},
              "coverage": {"with_daily": 2}}
    import json
    full = len(json.dumps(report, separators=(",", ":")))
    fitted = fit_size_budget(report, fresh_symbols={"FRESH1", "FRESH2"}, max_bytes=int(full * 0.45))
    assert set(fitted["symbols"]) >= {"FRESH1", "FRESH2"}
    assert fitted["size_budget"]["dropped_historical_symbols"] == ["OLD2", "OLD1"]
    assert fitted["size_budget"]["bars_capped"] is not None
    assert len(fitted["symbols"]["FRESH1"]["intervals"]["5m"]["bars"]) < 110
    assert fitted["symbols"]["FRESH1"]["intervals"]["5m"]["bars"][-1]["time"] == 109  # newest kept
    assert fitted["coverage"]["with_daily"] == 2  # fresh count untouched
    assert fitted["coverage"]["historical_only_symbols"] == []

    small = {"symbols": {"A": item()}, "coverage": {}}
    assert fit_size_budget(small, fresh_symbols={"A"}, max_bytes=10**7)["size_budget"]["bars_capped"] is None
    import pytest
    with pytest.raises(ValueError):
        fit_size_budget({"symbols": {"A": item()}, "coverage": {}}, fresh_symbols={"A"}, max_bytes=500)
