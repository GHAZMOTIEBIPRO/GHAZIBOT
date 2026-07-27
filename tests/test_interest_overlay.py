from __future__ import annotations

import pandas as pd

from options_radar.interest_overlay import advanced_interest_profile


def _history(rows: int = 80) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="B")
    close = pd.Series([100 + i * 0.25 for i in range(rows)], index=index, dtype=float)
    volume = pd.Series([1_000_000.0] * rows, index=index)
    volume.iloc[-5:] = 2_200_000.0
    frame = pd.DataFrame(
        {
            "Open": close * 0.997,
            "High": close * 1.012,
            "Low": close * 0.99,
            "Close": close,
            "Volume": volume,
        }
    )
    frame.iloc[-1, frame.columns.get_loc("High")] = close.iloc[-1] * 1.04
    frame.iloc[-1, frame.columns.get_loc("Close")] = close.iloc[-1] * 1.035
    return frame


def test_advanced_attention_detects_volume_acceleration_and_trend_quality():
    profile = advanced_interest_profile(_history())
    assert profile["volume_acceleration_5d"] >= 1.8
    assert profile["attention_score"] > 0
    assert profile["call_interest_score"] >= profile["put_interest_score"]
    assert any("تسارع حجم" in item for item in profile["attention_factors"])
    assert profile["attention_method"].startswith("Finviz-style")
