"""Confirmation study: completed buckets only, no look-ahead, honest outcomes and statistics."""
from datetime import datetime, timedelta, timezone

import pytest

from options_radar import confirmation_study as cs

OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)
PRIOR = {"high": 110.0, "low": 100.0, "close": 105.0}


def _session(path, vol=1000):
    """1-minute bars from a list of closes; each bar spans +-0.05 around its open/close."""
    bars, prev = [], path[0]
    for i, c in enumerate(path):
        bars.append({"t": OPEN + timedelta(minutes=i), "o": prev, "h": max(prev, c) + 0.05,
                     "l": min(prev, c) - 0.05, "c": c, "v": vol})
        prev = c
    return bars


def _hours(n=30, start=95.0, step=0.2):
    return [{"t": OPEN - timedelta(hours=n - i), "end": OPEN - timedelta(hours=n - i - 1), "c": start + i * step}
            for i in range(n)]


def _rally(break_minute=30, total=390):
    """Flat at 105 until the breakout minute, then a climb above 110 that reaches 112.72 (T1)."""
    pre = [105 + (5.3 * i / break_minute) for i in range(break_minute)]
    post = [110.3 + 0.012 * i for i in range(total - break_minute)]
    return pre + post


def test_buckets_are_session_aligned_and_drop_incomplete_ones():
    bars = _session([105.0] * 390)
    assert len(cs.bucket(bars, OPEN, 60)) == 6  # 15:30-16:00 has 30 of 60 minutes: not completed
    assert len(cs.bucket(bars, OPEN, 3)) == 130 and len(cs.bucket(bars[:-1], OPEN, 3)) == 129


def test_shorter_frames_enter_earlier_and_every_rule_is_scored_after_its_entry():
    signals = cs.session_signals(_session(_rally()), OPEN, PRIOR, 4.0, None, _hours())
    calls = {s.rule: s for s in signals if s.side == "CALL" and s.stop_model == "map"}
    assert {"C3", "C5", "C10", "C15", "C30", "C60", "H1F"} <= set(calls)
    mins = [calls[f"C{m}"].minutes_after_open for m in cs.FRAMES]
    assert mins == sorted(mins) and calls["C60"].minutes_after_open == 60
    assert all(s.outcome == "T1" and s.r > 0 for s in calls.values())
    # a later entry has already used more of the move: larger pre-confirmation distance
    assert calls["C60"].preconf_atr > calls["C3"].preconf_atr


def test_scoring_refuses_a_bar_that_started_before_the_entry():
    bars = _session([105.0] * 10)
    with pytest.raises(ValueError, match="look-ahead"):
        cs._score(bars, "CALL", 105.0, 104.0, 106.0, 105.0, OPEN + timedelta(minutes=5))


def test_same_bar_target_and_stop_is_ambiguous_never_a_win():
    path = [105.0] * 5 + [110.4] * 385
    bars = _session(path)
    bars[20].update(h=113.0, l=108.5)  # one bar touches both T1 (112.72) and the map stop (109)
    signals = cs.session_signals(bars, OPEN, PRIOR, 4.0, None, _hours())
    c3 = next(s for s in signals if s.rule == "C3" and s.side == "CALL" and s.stop_model == "map")
    assert c3.outcome == "AMBIGUOUS" and c3.r == 0.0


def test_false_breakout_is_stopped_early_and_counted():
    path = [105.0] * 10 + [110.5] * 5 + [108.0] * 375  # breaks out, then falls back through the stop
    signals = cs.session_signals(_session(path), OPEN, PRIOR, 4.0, None, _hours())
    c3 = next(s for s in signals if s.rule == "C3" and s.side == "CALL" and s.stop_model == "map")
    assert c3.outcome == "STOP" and c3.stopped_within_30m and c3.r < -1
    assert cs.summarise(signals)["C3/map"]["false_break_30m"] > 0


def test_retest_needs_a_touch_that_holds_and_rvol_needs_volume():
    # breakout at minute 10, retest of 110 around minute 40 that closes above, then a rise
    path = [105.0] * 10 + [111.0] * 25 + [110.2] * 10 + [111.0 + 0.01 * i for i in range(345)]
    bars = _session(path)
    signals = cs.session_signals(bars, OPEN, PRIOR, 4.0, None, _hours(),
                                 volume_baseline={(5, i): 100.0 for i in range(80)} | {(15, i): 1e9 for i in range(30)})
    rules = {s.rule for s in signals if s.side == "CALL"}
    assert "R5" in rules and "V5" in rules and "V15" not in rules  # 15m volume below 1.5 x its baseline
    r5 = next(s for s in signals if s.rule == "R5" and s.stop_model == "map")
    assert r5.minutes_after_open > next(s for s in signals if s.rule == "C5").minutes_after_open


def test_summary_explains_win_rate_vs_expectancy_without_prices():
    path = [105.0] * 10 + [110.5] * 5 + [108.0] * 375
    rally = cs.session_signals(_session(_rally()), OPEN, PRIOR, 4.0, None, _hours())
    fail = cs.session_signals(_session(path), OPEN, PRIOR, 4.0, None, _hours())
    s = cs.summarise(rally + fail)["C3/map"]
    assert s["n"] == 2 and s["win_rate"] == 0.5 and s["avg_loss_r"] < -1 < 0 < s["avg_win_r"]
    assert s["exp_r"] == round((s["avg_win_r"] + s["avg_loss_r"]) / 2, 3)
    assert {"pf", "mfe_r", "mae_r", "preconf_atr", "by_entry_time", "by_volatility"} <= set(s)
    assert "110" not in str(s)
