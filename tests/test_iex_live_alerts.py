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
    assert st.latency_summary() == {"alerts": 1, "p50_s": 4.0, "p95_s": 4.0, "max_s": 4.0}
    bars = [{"t": OPEN + timedelta(minutes=5 * i), "v": 100.0 * (i + 1)} for i in range(3)]
    assert live.baseline_from_bars(bars, [(OPEN, OPEN + timedelta(hours=1))]) == {0: 100.0, 1: 200.0, 2: 300.0}
