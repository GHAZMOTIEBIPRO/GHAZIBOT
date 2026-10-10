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

def _long_vcp_history() -> pd.DataFrame:
    index = pd.date_range("2025-08-01", periods=240, freq="B", tz="UTC")
    base = np.linspace(20.0, 39.0, 220)
    tail = np.array([
        39.00, 39.30, 39.10, 39.38, 39.22,
        39.42, 39.30, 39.46, 39.36, 39.49,
        39.40, 39.51, 39.44, 39.53, 39.47,
        39.55, 39.50, 39.57, 39.53, 39.59,
    ])
    close = np.concatenate([base, tail])
    width = np.concatenate([
        np.full(220, 0.55),
        np.linspace(0.24, 0.07, 20),
    ])
    high = close + width
    low = close - width
    volume = np.concatenate([
        np.full(220, 1_200_000.0),
        np.linspace(850_000.0, 420_000.0, 20),
    ])
    return pd.DataFrame(
        {
            "Open": close - 0.02,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_explosion_setup_v3_exposes_vcp_structure_without_changing_live_score():
    snapshot = analyze_breakout_pressure(
        _long_vcp_history(),
        "call",
        relative_strength_20d=0.05,
    )

    v3 = snapshot.research_v3
    assert isinstance(v3, dict)
    assert v3["research_only"] is True
    assert v3["live_score_adjustment"] is False
    assert v3["decision_authority"] is False
    assert v3["ema200_available"] is True
    assert isinstance(v3["quality_flags"]["vcp_like"], bool)
    assert 0 <= v3["hh_hl_structure_ratio"] <= 1
    assert v3["distance_to_52w_extreme_pct"] is not None
    assert v3["stage"] in {"ARMED", "COILING", "RESEARCH", "EXTENDED"}

