"""Confirmation-timeframe study: completed buckets only, no look-ahead, honest outcomes."""
from datetime import datetime, timedelta, timezone

from options_radar import confirmation_study as cs

OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)
PRIOR = {"high": 110.0, "low": 100.0, "close": 105.0}


def _session(path):
    """5m bars from a list of closes; each bar spans +-0.1 around its open/close."""
    bars, prev = [], path[0]
    for i, c in enumerate(path):
        bars.append({"t": OPEN + timedelta(minutes=5 * i), "o": prev, "h": max(prev, c) + 0.1,
                     "l": min(prev, c) - 0.1, "c": c, "v": 1000})
        prev = c
    return bars


def _hours(n=30, start=95.0, step=0.2):
    return [{"t": OPEN - timedelta(hours=n - i), "end": OPEN - timedelta(hours=n - i - 1), "o": start + i * step,
             "h": start + i * step + 0.5, "l": start + i * step - 0.5, "c": start + i * step} for i in range(n)]


def test_buckets_are_session_aligned_and_drop_incomplete_ones():
    bars = _session([105.0] * 78)
    assert len(cs.bucket(bars, OPEN, 60)) == 6  # 15:30-16:00 has 6 of 12 bars: not completed
    assert len(cs.bucket(bars, OPEN, 15)) == 26 and len(cs.bucket(bars[:-1], OPEN, 15)) == 25


def test_faster_frames_enter_earlier_and_outcomes_are_scored_without_look_ahead():
    # breakout above 110 at 10:00 (bar 6), then a steady climb to T1 and beyond
    path = [105 + i * 0.8 for i in range(7)] + [110.5 + i * 0.15 for i in range(71)]
    signals = cs.session_signals(_session(path), OPEN, PRIOR, atr14=4.0, week=None, prior_hours=_hours())
    calls = {s.method: s for s in signals if s.side == "CALL"}
    assert set(calls) == {"H1", "M15", "M5", "H1F_M15_M5"}
    assert calls["M5"].minutes_after_open < calls["M15"].minutes_after_open < calls["H1"].minutes_after_open
    assert calls["H1"].minutes_after_open == 60  # first completed hour closes at 10:30
    # T1 = 110 + 0.272 x 10 = 112.72; every method reaches it before the 109 invalidation
    assert all(s.outcome == "T1" for s in calls.values()) and all(s.r > 0 for s in calls.values())
    assert not [s for s in signals if s.side == "PUT"]


def test_gap_past_the_first_target_is_not_a_free_hit():
    """Regression (first runner run): a gap above T1 was scored as T1 reached with positive R."""
    path = [113.5, 113.6, 113.4] + [113.5] * 75  # opens above T1 112.72, drifts sideways
    signals = cs.session_signals(_session(path), OPEN, PRIOR, atr14=4.0, week=None, prior_hours=_hours())
    m5 = next(s for s in signals if s.method == "M5" and s.side == "CALL")
    assert m5.outcome != "T1" or m5.r > 0
    assert m5.outcome in ("CLOSE", "STOP")  # next target 114.0 never reached
    assert all(s.r <= 1 for s in signals)


def test_same_bar_target_and_stop_is_ambiguous_never_a_win():
    path = [105.0] * 5 + [110.4] + [110.4] * 72
    bars = _session(path)
    # one wide bar after the breakout touches both T1 (112.72) and the stop (109)
    bars[10].update(h=113.0, l=108.5)
    signals = cs.session_signals(bars, OPEN, PRIOR, atr14=4.0, week=None, prior_hours=_hours())
    m5 = next(s for s in signals if s.method == "M5" and s.side == "CALL")
    assert m5.outcome == "AMBIGUOUS" and m5.r == 0.0
    summary = cs.summarise(signals)
    assert summary["M5"]["ambiguous_same_bar"] == 1 and summary["M5"]["t1_first"] == 0


def test_hour_trend_filter_blocks_a_breakout_against_the_hour_trend():
    path = [105 + i * 0.8 for i in range(7)] + [110.5] * 71
    falling = _hours(start=130.0, step=-0.5)  # hour closes far below their EMA20 side for a CALL
    signals = cs.session_signals(_session(path), OPEN, PRIOR, atr14=4.0, week=None, prior_hours=falling)
    assert not [s for s in signals if s.method == "H1F_M15_M5"]
    assert [s for s in signals if s.method == "M15"]  # the unfiltered rule still fires


def test_summary_holds_statistics_only():
    path = [105 + i * 0.8 for i in range(7)] + [110.5 + i * 0.15 for i in range(71)]
    summary = cs.summarise(cs.session_signals(_session(path), OPEN, PRIOR, 4.0, None, _hours()))
    assert set(summary) == set(cs.METHODS)
    assert set(summary["M5"]) >= {"signals", "t1_first", "stop_first", "avg_r", "median_entry_minutes_after_open"}
    assert "110" not in str(summary) and "entry" not in str(summary).replace("entry_minutes", "").replace("entered", "")
