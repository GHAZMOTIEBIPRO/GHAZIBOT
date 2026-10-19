"""MIT pandas-ta-classic research adapter: no executable quote or invented trend."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from options_radar.pandas_ta_bollinger_shadow import bollinger_compression_shadow
from scripts.build_stock_watch_charts import pack_symbol


def candles(n: int = 100, compressed: bool = False) -> pd.DataFrame:
    days = pd.bdate_range(end="2026-10-15", periods=n, tz="America/New_York")
    step = np.arange(n)
    close = 100 + 3 * np.sin(step / 2.5)
    if compressed:
        close[-24:] = 100 + .02 * np.sin(step[-24:] / 2.5)
    return pd.DataFrame(
        {
            "Open": close - 0.05,
            "High": close + 0.4,
            "Low": close - 0.45,
            "Close": close,
            "Volume": np.full(n, 10000),
        },
        index=days,
    )


def test_real_open_source_package_produces_dated_bollinger_width():
    result = bollinger_compression_shadow(candles())
    assert result["available"] is True
    assert result["library"] == "xgboosted/pandas-ta-classic"
    assert result["status"] in ("NORMAL_WIDTH", "COMPRESSION_WATCH")
    assert result["source_last_daily_bar"] == "2026-10-15"
    assert result["width_pct"] >= 0
    assert result["percentile_threshold_pct"] > 0
    assert result["price_probability"] is None
    assert result["research_only"] is True
    assert result["independent_data_confirmation"] is False
    assert result["live_decision_authority"] is False
    assert result["options_execution_eligible"] is False


def test_narrow_recent_bars_produce_compression_monitor_not_call_signal():
    narrow = bollinger_compression_shadow(candles(compressed=True))
    assert narrow["available"] is True
    assert narrow["compression_watch"] is True
    assert narrow["status"] == "COMPRESSION_WATCH"
    assert narrow["live_decision_authority"] is False


def test_missing_invalid_and_noncausal_inputs_fail_closed():
    base = candles(70)
    cases = [
        pd.DataFrame(),
        candles(40),
        base.assign(Close=0),
        base.assign(Close=float("inf")),
        base.iloc[::-1],
        pd.concat([base, base.iloc[[-1]]]),
        base.drop(columns=["High"]),
    ]
    for frame in cases:
        snapshot = bollinger_compression_shadow(frame)
        assert snapshot["available"] is False
        assert snapshot["compression_watch"] is None
        assert snapshot["options_execution_eligible"] is False


def test_optional_library_absent_is_honest(monkeypatch):
    from options_radar import pandas_ta_bollinger_shadow as module
    def no_library(_name):
        raise ImportError("offline")
    monkeypatch.setattr(module, "import_module", no_library)
    out = module.bollinger_compression_shadow(candles())
    assert out["available"] is False
    assert out["reason"] == "OPTIONAL_LIBRARY_NOT_INSTALLED"


def test_integration_does_not_mislabel_same_yahoo_source_as_independent():
    time = datetime(2026, 10, 16, 15, 46, tzinfo=ZoneInfo("America/New_York"))
    daily = candles()
    result = pack_symbol("RGC", daily, None, None, now=time)
    assert result is not None
    shadow = result["volatility_shadow"]
    assert shadow["available"] is True
    assert shadow["data_source_family"] == "yahoo"
    assert shadow["independent_data_confirmation"] is False
    assert shadow["source_last_daily_bar"] == "2026-10-15"
    assert result["options_execution_grade"] is False


def test_research_dependency_only_in_dedicated_workflow():
    wf = Path(".github/workflows/stock-watch-charts.yml").read_text(encoding="utf-8")
    js = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    req = Path("requirements-dev.txt").read_text(encoding="utf-8")
    assert "pandas-ta-classic==0.8.32" in wf
    assert "pandas-ta-classic==0.8.32" in req
    assert "volatility_shadow" in js
    assert "انكماش بحثي" in js
    assert "live_decision_authority" not in js  # No release gate upgrades.
