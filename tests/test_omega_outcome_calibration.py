from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from options_radar.calibration import build_calibration_report
from options_radar.outcomes import evaluate_option_path, evaluate_underlying_path


def _bars(rows):
    index = pd.date_range("2026-09-01T14:30:00Z", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, index=index)


def test_option_path_target_before_stop_is_success():
    signal = {
        "signal_time": "2026-09-01T14:30:00Z",
        "option_type": "call",
        "target_1": 2.0,
        "target_2": 2.5,
        "stop_price": 0.8,
    }
    result = evaluate_option_path(
        signal,
        _bars([
            {"Open": 1.0, "High": 1.4, "Low": 0.95, "Close": 1.3, "Volume": 10},
            {"Open": 1.3, "High": 2.1, "Low": 1.2, "Close": 2.0, "Volume": 10},
        ]),
    )
    assert result["terminal_outcome"] == "success"
    assert result["outcome_order"] == "target_1_first"


def test_same_bar_target_and_stop_is_ambiguous():
    signal = {
        "signal_time": "2026-09-01T14:30:00Z",
        "option_type": "call",
        "target_1": 2.0,
        "target_2": 2.5,
        "stop_price": 0.8,
    }
    result = evaluate_option_path(
        signal,
        _bars([
            {"Open": 1.0, "High": 2.1, "Low": 0.7, "Close": 1.1, "Volume": 10},
        ]),
    )
    assert result["terminal_outcome"] == "ambiguous"
    assert result["ambiguous_same_bar"] is True


def test_underlying_put_uses_inverse_bar_direction():
    signal = {
        "signal_time": "2026-09-01T14:30:00Z",
        "option_type": "put",
        "underlying_target_1": 90.0,
        "underlying_target_2": 85.0,
        "underlying_invalidation": 105.0,
    }
    result = evaluate_underlying_path(
        signal,
        _bars([
            {"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 10},
            {"Open": 100, "High": 101, "Low": 89, "Close": 90, "Volume": 10},
        ]),
    )
    assert result["terminal_outcome"] == "success"


def test_calibration_waits_for_maturity(tmp_path: Path):
    signals = tmp_path / "signals.jsonl"
    outcomes = tmp_path / "outcomes.json"
    signals.write_text(json.dumps({
        "signal_id": "s1", "score": 90, "catalyst": "news:test"
    }) + "\n", encoding="utf-8")
    outcomes.write_text(json.dumps({
        "signals": {"s1": {"observations": 1, "checkpoints": {}}}
    }), encoding="utf-8")
    report = build_calibration_report(signals, outcomes, minimum_sample=1)
    assert report["calibration_ready"] is False
    assert report["matured_sample"] == 0
