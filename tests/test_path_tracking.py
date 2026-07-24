from __future__ import annotations

import pandas as pd

from options_radar.journal import evaluate_underlying_path


def _bars(rows):
    index = pd.date_range("2026-07-24 14:00:00+00:00", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, index=index)


def test_call_target_is_recorded_before_later_stop():
    signal = {
        "signal_time": "2026-07-24T14:00:00+00:00",
        "option_type": "call",
        "underlying_target_1": 105,
        "underlying_target_2": 110,
        "underlying_invalidation": 95,
    }
    bars = _bars([
        {"Open": 100, "High": 103, "Low": 99, "Close": 102, "Volume": 1},
        {"Open": 102, "High": 106, "Low": 101, "Close": 105, "Volume": 1},
        {"Open": 105, "High": 106, "Low": 94, "Close": 96, "Volume": 1},
    ])
    result = evaluate_underlying_path(signal, bars)
    assert result["outcome_order"] == "target_1_first"
    assert result["first_target_1_at"].endswith("14:05:00+00:00")
    assert result["first_stop_at"].endswith("14:10:00+00:00")


def test_same_bar_target_and_stop_is_ambiguous_not_a_win():
    signal = {
        "signal_time": "2026-07-24T14:00:00+00:00",
        "option_type": "call",
        "underlying_target_1": 105,
        "underlying_target_2": 110,
        "underlying_invalidation": 95,
    }
    bars = _bars([
        {"Open": 100, "High": 106, "Low": 94, "Close": 101, "Volume": 1},
    ])
    result = evaluate_underlying_path(signal, bars)
    assert result["outcome_order"] == "ambiguous_same_bar"
    assert result["ambiguous_same_bar"] is True


def test_put_uses_low_for_targets_and_high_for_stop():
    signal = {
        "signal_time": "2026-07-24T14:00:00+00:00",
        "option_type": "put",
        "underlying_target_1": 95,
        "underlying_target_2": 90,
        "underlying_invalidation": 105,
    }
    bars = _bars([
        {"Open": 100, "High": 102, "Low": 94, "Close": 96, "Volume": 1},
        {"Open": 96, "High": 106, "Low": 93, "Close": 104, "Volume": 1},
    ])
    result = evaluate_underlying_path(signal, bars)
    assert result["outcome_order"] == "target_1_first"
