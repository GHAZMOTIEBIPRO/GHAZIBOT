"""IEX live first-look: completed 5m buckets only, like-for-like RVOL, one alert per side, latency."""
from datetime import datetime, timedelta, timezone

from options_radar import iex_live_alerts as live

OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)


def _state():
    return live.LiveState(open_at=OPEN, levels={"NVDA": {"call": 110.0, "put": 100.0}},
                          baseline={"NVDA": {i: 1000.0 for i in range(80)}})


def _feed(st, minute, close, vol, delay=2.0):
    start = OPEN + timedelta(minutes=minute)
    return st.on_bar("NVDA", start, close, close + 0.1, close - 0.1, close, vol,
                     received_at=start + timedelta(seconds=60 + delay))


def test_alert_only_when_the_bucket_completes_beyond_trigger_with_volume():
    st = _state()
    for m in range(4):
        assert _feed(st, m, 110.5, 400) == []  # bucket not complete
    out = _feed(st, 4, 110.6, 400)  # 2000 >= 1.5 x 1000
    assert len(out) == 1 and out[0]["side"] == "CALL" and out[0]["latency_s"] == 2.0
    assert out[0]["bucket_end"] == (OPEN + timedelta(minutes=5)).isoformat()
    for m in range(5, 10):
        later = _feed(st, m, 111.0, 400)
    assert later == []  # one alert per symbol and side per day


def test_low_volume_or_missing_minute_blocks_the_alert():
    st = _state()
    for m in range(5):
        out = _feed(st, m, 110.5, 100)
    assert out == []  # 500 < 1.5 x 1000
    st2 = _state()
    for m in (5, 6, 8, 9):  # minute 7 missing on IEX
        out = _feed(st2, m, 110.5, 1000)
    assert out == []


def test_latency_summary_and_baseline():
    st = _state()
    for m in range(5):
        _feed(st, m, 99.0, 500, delay=4.0)
    summary = st.latency_summary()
    assert summary["alerts"] == 1 and summary["alert"] == {"n": 1, "p50_s": 4.0, "p95_s": 4.0, "max_s": 4.0}
    assert summary["feed"]["n"] >= 5 and summary["send"] == {"n": 0}
    bars = [{"t": OPEN + timedelta(minutes=5 * i), "v": 100.0 * (i + 1)} for i in range(3)]
    assert live.baseline_from_bars(bars, [(OPEN, OPEN + timedelta(hours=1))]) == {0: 100.0, 1: 200.0, 2: 300.0}


def _aaa_state():
    from datetime import datetime, timezone

    open_at = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)
    return open_at, live.LiveState(open_at=open_at, levels={"AAA": {"call": 10.0, "put": 5.0}},
                                   baseline={"AAA": {0: 100.0}})


def _aaa_feed(st, open_at, *, source="stream", silent=False, minutes=range(5)):
    from datetime import timedelta

    out = []
    for m in minutes:
        start = open_at + timedelta(minutes=m)
        out += st.on_bar("AAA", start, 10, 11, 9.5, 10.5, 40, start + timedelta(minutes=1, seconds=3),
                         source=source, silent=silent)
    return out


def test_duplicate_bars_never_fire_twice_and_backfill_fills_a_gap():
    open_at, st = _aaa_state()
    assert _aaa_feed(st, open_at, minutes=range(4)) == []          # minute 4 lost in a reconnect
    alerts = _aaa_feed(st, open_at, source="rest", minutes=range(5))  # REST backfill of the window
    assert len(alerts) == 1 and alerts[0]["source"] == "rest"
    assert _aaa_feed(st, open_at, minutes=range(5)) == [] and _aaa_feed(st, open_at, source="rest") == []
    assert st.backfilled_bars == 1 and st.latency_summary()["feed"]["n"] == 9


def test_silent_replay_marks_handled_buckets_without_alerting():
    open_at, st = _aaa_state()
    assert _aaa_feed(st, open_at, source="rest", silent=True) == []
    assert ("AAA", "call") in st.fired and st.replayed_fired == 1
    assert _aaa_feed(st, open_at) == []  # the stream repeating the same bucket stays quiet


def test_segments_cover_the_session_without_overlap_or_gap():
    from datetime import datetime, timedelta, timezone

    from scripts import run_iex_stream as rs

    open_at = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)
    close_at = open_at + timedelta(minutes=390)
    first = rs.segment_plan(open_at - timedelta(minutes=2), open_at, close_at, 345)
    assert first["action"] == "listen" and not first["replay"] and first["stop_at"] == open_at + timedelta(minutes=343)
    late = rs.segment_plan(open_at + timedelta(minutes=20), open_at, close_at, 345)
    assert late["replay"] and not late["silent_replay"]  # nothing ran before it: its replay alerts
    second = rs.segment_plan(first["stop_at"] + timedelta(seconds=40), open_at, close_at, 345)
    assert second["replay"] and second["silent_replay"] and second["stop_at"] == close_at + timedelta(minutes=1)
    assert rs.segment_plan(close_at + timedelta(minutes=2), open_at, close_at, 345)["action"] == "exit"
    early_close = open_at + timedelta(minutes=210)  # 13:00 New York
    assert rs.segment_plan(open_at, open_at, early_close, 345)["stop_at"] == early_close + timedelta(minutes=1)
