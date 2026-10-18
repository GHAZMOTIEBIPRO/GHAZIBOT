"""Historic chart retention is bounded, source-validated and never fresh."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from scripts.build_stock_watch_charts import collect, pack_symbol
from scripts.stock_chart_retention import retain_valid_history

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
SOURCE = "Yahoo Finance yfinance (unofficial research, may be delayed)"


def frame(tz="America/New_York"):
    idx = pd.bdate_range(end="2026-10-16", periods=65, tz=tz)
    vals = [11 + .05 * i for i in range(len(idx))]
    return pd.DataFrame({
        "Open": vals,
        "High": [v + .5 for v in vals],
        "Low": [v - .5 for v in vals],
        "Close": vals,
        "Volume": [100] * len(idx),
    }, index=idx)


def previous_report(symbol="NEWX"):
    item = pack_symbol(symbol, frame(), None, None, now=NOW,
                       dynamic_watch=(symbol,))
    assert item is not None
    return {
        "schema": "ghazi.stock_charts.v1",
        "generated_at": NOW.isoformat(),
        "data_role": "RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
        "provider_source_family": "yahoo",
        "quote_execution_eligible": False,
        "symbols": {symbol: item},
    }


def test_rotated_stock_keeps_real_past_bars_but_never_live_status():
    prior = previous_report()
    original = copy.deepcopy(prior["symbols"]["NEWX"]["intervals"]["1d"]["bars"])
    merged, kept, count = retain_valid_history(
        prior, {}, now=NOW + timedelta(hours=6), actively_scanned=(),
    )
    assert kept == ["NEWX"] and count == 1
    item = merged["NEWX"]
    assert item["historical_cache_only"] is True
    assert item["options_execution_grade"] is False
    assert item["intervals"]["1d"]["current_session_confirmed"] is False
    assert item["intervals"]["1d"]["bars"] == original
    assert item["cached_source_generated_at"] == NOW.isoformat()
    assert prior["symbols"]["NEWX"]["intervals"]["1d"].get("historical_cache_only") is None


def test_previously_retained_candle_cannot_refresh_itself_forever():
    prior = previous_report()
    merged, kept, _ = retain_valid_history(
        prior, {}, now=NOW + timedelta(days=3), actively_scanned=(),
    )
    assert kept == ["NEWX"]
    latest = dict(prior, generated_at=(NOW + timedelta(days=3)).isoformat(),
                  symbols=merged)
    result, kept_again, _ = retain_valid_history(
        latest, {}, now=NOW + timedelta(days=8), actively_scanned=(),
    )
    assert result == {} and kept_again == []


def test_rejects_fake_future_prices_and_corrupted_cache():
    for change in [
        lambda f: f["bars"][-1].update(close=float("nan")),
        lambda f: f["bars"][-1].update(low=1000),
        lambda f: f["bars"][-1].update(time="2029-01-01"),
        lambda f: f.update(provider_bar_start_or_date="2022-01-01"),
        lambda f: f["bars"].append(f["bars"][-1].copy()),
        lambda f: f.update(research_only=False),
    ]:
        old = previous_report()
        change(old["symbols"]["NEWX"]["intervals"]["1d"])
        got, kept, _ = retain_valid_history(old, {}, now=NOW, actively_scanned=())
        assert got == {} and kept == []


def test_forged_provider_and_old_report_are_rejected():
    for key, value in [
        ("provider_source_family", "other_provider"),
        ("quote_execution_eligible", True),
        ("schema", "unknown"),
        ("generated_at", (NOW + timedelta(hours=2)).isoformat()),
        ("generated_at", (NOW - timedelta(days=9)).isoformat()),
    ]:
        old = previous_report()
        old[key] = value
        result, retained, count = retain_valid_history(
            old, {}, now=NOW, actively_scanned=(),
        )
        assert result == {} and retained == [] and count == 0


def test_active_symbol_keeps_current_bars_and_only_backfills_missing_timeframe():
    old = previous_report("RGC")
    current = copy.deepcopy(old["symbols"]["RGC"])
    current["intervals"] = {"15m": {
        "bars": [], "research_only": True,
        "current_session_confirmed": True,
    }}
    result, retained, count = retain_valid_history(
        old, {"RGC": current}, now=NOW, actively_scanned=("RGC",),
    )
    assert retained == ["RGC"] and count == 1
    assert result["RGC"]["intervals"]["15m"]["current_session_confirmed"] is True
    assert result["RGC"]["intervals"]["1d"]["historical_cache_only"] is True
    assert result["RGC"].get("historical_cache_only") is None


def test_collector_reports_historical_separate_from_fresh():
    old = previous_report("NEWX")
    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol
        def history(self, *, period, interval, auto_adjust, prepost):
            if self.symbol == "NEWX":
                return pd.DataFrame()
            return frame() if interval == "1d" else pd.DataFrame()
    report = collect(
        now=NOW, provider=SimpleNamespace(Ticker=Ticker),
        delay=lambda _: None, dynamic_symbols=("NEWX",), previous=old,
    )
    coverage = report["coverage"]
    assert coverage["requested"] == 17
    assert coverage["with_valid_charts"] == 16
    assert coverage["retained_symbols"] == ["NEWX"]
    assert coverage["historical_only_symbols"] == ["NEWX"]
    assert coverage["charts_including_historical"] == 17
    assert report["symbols"]["NEWX"]["historical_cache_only"] is True
    assert report["quote_execution_eligible"] is False


def test_frontend_displays_cache_warning_without_rewriting_provider_date():
    text = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert "frame?.historical_cache_only===true" in text
    assert "frame.cached_source_generated_at" in text
    assert "شموع محفوظة من فحص سابق" in text
    assert "retained_symbols_count" in text
