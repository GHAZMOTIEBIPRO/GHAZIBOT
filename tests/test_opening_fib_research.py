"""Synthetic-only regression checks for isolated opening-Fib research lab."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from research.opening_fib_omega.orb_research_lab import (
    describe, level_spec, load_csv, prepare_sessions, trade_one
)

BASE = datetime(2026, 11, 16, 14, 30, tzinfo=timezone.utc)


def sample():
    bars = []
    for minute in range(0, 390, 5):
        bars.append({
            "symbol": "SPY", "timestamp": BASE + timedelta(minutes=minute),
            "open": 100.0, "high": 100.25, "low": 99.75,
            "close": 100.0, "volume": 50000.0
        })
    bars[0].update(open=100.0, high=100.5, low=99.0, close=100.2)
    bars[1].update(open=100.2, high=101.0, low=100.0, close=100.9)
    bars[2].update(open=100.9, high=101.0, low=99.8, close=100.6)
    bars[3].update(open=100.8, high=101.12, low=100.8, close=101.05)
    bars[4].update(open=101.05, high=101.22, low=101.0, close=101.1)
    bars[5].update(open=101.15, high=102.4, low=101.1, close=102.3)
    frame = pd.DataFrame(bars)
    frame["ny_minute"] = 570 + frame.index * 5
    return frame


def test_valid_calendar_session():
    sessions, excluded = prepare_sessions(sample())
    assert not excluded and len(sessions) == 1
    assert len(sessions[0][2]) == 78


def test_missing_bar_is_rejected():
    sessions, excluded = prepare_sessions(sample().drop(index=7))
    assert not sessions
    assert excluded["MISSING_OR_NON_5M_BARS"] == 1


def test_signal_time_is_close_and_entry_next_open():
    b = sample()
    t = trade_one("SPY", "2026-11-16", b, window=15,
                  model="ORB", levels="fib", cost_bps=12)
    assert t is not None and t.side == 1
    assert t.signal_at_utc == (b.iloc[4]["timestamp"] + pd.Timedelta(minutes=5)).isoformat()
    assert t.fill_at_utc == b.iloc[5]["timestamp"].isoformat()
    assert t.exit_cause == "TARGET2"


def test_same_candle_stop_and_target_stop_first():
    b = sample()
    b.loc[5, "low"] = 100.1
    t = trade_one("SPY", "2026-11-16", b, window=15,
                  model="ORB", levels="fib", cost_bps=12)
    assert t is not None and t.exit_cause == "STOP" and t.net_r < 0


def test_fib_reversal_has_feasible_stop_after_known_wicks():
    b = sample()
    b.loc[3, ["open", "high", "low", "close"]] = [99.68, 99.85, 99.62, 99.71]
    b.loc[4, ["open", "high", "low", "close"]] = [99.71, 99.97, 99.67, 99.93]
    b.loc[5, ["open", "high", "low", "close"]] = [99.94, 100.2, 99.89, 100.1]
    b.loc[6, ["open", "high", "low", "close"]] = [100.1, 101.2, 100.0, 101.1]
    t = trade_one("SPY", "2026-11-16", b, window=15,
                  model="Fib Reversal", levels="fib", cost_bps=12)
    assert t is not None and t.side == 1
    assert t.signal_at_utc == (b.iloc[4]["timestamp"] + pd.Timedelta(minutes=5)).isoformat()
    assert t.fill_at_utc == b.iloc[5]["timestamp"].isoformat()


def test_placebo_deterministic_and_all_statistics_not_proven():
    assert level_spec("SPY", "2026-11-16", "placebo") == level_spec(
        "SPY", "2026-11-16", "placebo"
    )
    assert describe([])["status"] == "NO_TRADES"


def test_naive_timestamp_rejected(tmp_path: Path):
    b = sample()
    b["timestamp"] = b["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    csv = tmp_path / "naive.csv"
    b.to_csv(csv, index=False)
    with pytest.raises(ValueError, match="UTC offset"):
        load_csv(csv)
