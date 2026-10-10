from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

from options_radar.open_source_research import (
    build_hindsight_safe_smc_snapshot,
    normalize_ohlcv,
)


class _FakeSmc:
    @classmethod
    def fvg(cls, ohlc, join_consecutive=False):
        frame = pd.DataFrame(
            {
                "FVG": np.nan,
                "Top": np.nan,
                "Bottom": np.nan,
                "MitigatedIndex": np.nan,
            },
            index=ohlc.index,
        )
        frame.loc[len(frame) - 3, ["FVG", "Top", "Bottom"]] = [1, 110.0, 108.0]
        frame.loc[len(frame) - 1, ["FVG", "Top", "Bottom"]] = [-1, 112.0, 111.0]
        return frame

    @classmethod
    def swing_highs_lows(cls, ohlc, swing_length=20):
        frame = pd.DataFrame({"HighLow": np.nan, "Level": np.nan}, index=ohlc.index)
        frame.loc[10, ["HighLow", "Level"]] = [-1, 95.0]
        frame.loc[len(frame) - 1, ["HighLow", "Level"]] = [1, 125.0]
        return frame


def _history(rows=80):
    index = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = np.linspace(100, 120, rows)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1000,
        },
        index=index,
    )


def test_normalize_ohlcv_lowercases_columns():
    frame = normalize_ohlcv(_history())
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]


def test_smc_snapshot_excludes_unconfirmed_tail(monkeypatch):
    monkeypatch.setitem(sys.modules, "smartmoneyconcepts", SimpleNamespace(smc=_FakeSmc))
    snapshot = build_hindsight_safe_smc_snapshot(_history(), swing_length=20)

    assert snapshot["live_decision_authority"] is False
    assert snapshot["safe_swing_cutoff_index"] == 59
    assert snapshot["last_confirmed_swing"]["index"] == 10
    assert snapshot["last_confirmed_fvg"]["index"] == 77
    assert snapshot["swing_confirmation_lag_bars"] == 20
