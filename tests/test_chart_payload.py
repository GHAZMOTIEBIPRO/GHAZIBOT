from __future__ import annotations

import pandas as pd

from options_radar.chart_payload import build_chart_bars, build_chart_bundle


def _history():
    index = pd.date_range("2026-01-01", periods=40, freq="D")
    return pd.DataFrame(
        {
            "Open": range(100, 140),
            "High": range(101, 141),
            "Low": range(99, 139),
            "Close": range(100, 140),
            "Volume": 1000,
        },
        index=index,
    )


def test_build_chart_bars_uses_stable_daily_schema():
    bars = build_chart_bars(_history(), max_bars=20)
    assert len(bars) == 20
    assert list(bars[0]) == ["time", "open", "high", "low", "close"]
    assert bars[-1]["time"] == "2026-02-09"


def test_build_chart_bundle_isolates_loader_failures():
    def loader(symbol, period="6mo"):
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return _history()

    charts, errors = build_chart_bundle(
        [
            {"symbol": "AAA", "target_1": 130, "target_2": 140, "stop": 95},
            {"symbol": "BAD"},
        ],
        loader,
        max_symbols=2,
        max_bars=20,
    )
    assert "AAA" in charts
    assert charts["AAA"]["levels"]["target_1"] == 130
    assert errors == {"BAD": "provider down"}
