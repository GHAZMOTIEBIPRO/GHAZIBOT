from __future__ import annotations

import numpy as np
import pandas as pd

from options_radar.breakout_pressure import analyze_breakout_pressure


def _coiling_history() -> pd.DataFrame:
    index = pd.date_range("2026-06-01", periods=80, freq="B", tz="UTC")
    first = np.linspace(20.0, 30.0, 70)
    last = np.array([30.00, 30.08, 30.04, 30.12, 30.10, 30.16, 30.14, 30.20, 30.18, 30.24])
    close = np.concatenate([first, last])
    high = close + np.concatenate([np.full(70, 0.45), np.full(10, 0.12)])
    low = close - np.concatenate([np.full(70, 0.45), np.full(10, 0.12)])
    volume = np.concatenate([np.full(70, 1_000_000.0), np.full(10, 550_000.0)])
    volume[-1] = 1_500_000.0
    return pd.DataFrame(
        {
            "Open": close - 0.03,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_breakout_pressure_rewards_compression_and_near_trigger_structure():
    snapshot = analyze_breakout_pressure(
        _coiling_history(),
        "call",
        relative_strength_20d=0.04,
    )

    assert snapshot.available is True
    assert snapshot.score >= 70
    assert snapshot.atr_compression_ratio is not None
    assert snapshot.atr_compression_ratio < 0.9
    assert snapshot.range_tightness_pct is not None
    assert snapshot.range_tightness_pct < 5
    assert snapshot.breakout_distance_atr is not None
    assert snapshot.breakout_distance_atr <= 0.8
    assert any("ATR compression" in reason for reason in snapshot.reasons)


def test_breakout_pressure_fails_closed_with_short_history():
    frame = _coiling_history().tail(10)
    snapshot = analyze_breakout_pressure(frame, "call")

    assert snapshot.available is False
    assert snapshot.score == 0
    assert "insufficient_history" in snapshot.reasons
