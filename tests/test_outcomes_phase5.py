from __future__ import annotations

import pandas as pd

from options_radar.outcomes import evaluate_option_path, evaluate_underlying_path


def _bars(rows):
    index = pd.date_range("2026-07-24 14:00:00+00:00", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, index=index)


def test_stop_first_is_terminal_failure_even_if_later_target_hits():
    signal = {
        "signal_time": "2026-07-24T14:00:00+00:00",
        "option_type": "call",
        "underlying_target_1": 105,
        "underlying_target_2": 110,
        "underlying_invalidation": 95,
    }
    bars = _bars([
        {"Open": 100, "High": 102, "Low": 94, "Close": 96, "Volume": 1},
        {"Open": 96, "High": 111, "Low": 96, "Close": 110, "Volume": 1},
    ])
    result = evaluate_underlying_path(signal, bars)
    assert result["outcome_order"] == "stop_first"
    assert result["terminal_outcome"] == "failed"
    assert result["terminal_reason"] == "stopped_out_before_target_1"


def test_same_bar_is_ambiguous_and_never_success():
    signal = {
        "signal_time": "2026-07-24T14:00:00+00:00",
        "target_1": 2.0,
        "target_2": 3.0,
        "stop_price": 1.0,
    }
    bars = _bars([
        {"Open": 1.5, "High": 2.1, "Low": 0.9, "Close": 1.8, "Volume": 1},
    ])
    result = evaluate_option_path(signal, bars, bar_resolution="1d")
    assert result["terminal_outcome"] == "ambiguous"
    assert result["ambiguous_same_bar"] is True
