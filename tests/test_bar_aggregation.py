"""Session-aligned frames from 5-minute bars: completed buckets only, early close respected."""
from datetime import datetime, timedelta, timezone

from options_radar.bar_aggregation import aggregate, frames_from_5m

UTC = timezone.utc


def _bars(start, n):
    return [{"t": start + timedelta(minutes=5 * i), "o": 10.0, "h": 10.5, "l": 9.5, "c": 10.0 + i * 0.01, "v": 100}
            for i in range(n)]


def test_buckets_follow_the_session_and_skip_the_unfinished_one():
    open_, close = datetime(2026, 10, 26, 13, 30, tzinfo=UTC), datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
    premarket = _bars(datetime(2026, 10, 26, 12, 0, tzinfo=UTC), 18)  # 08:00-09:30 NY, ignored
    bars = premarket + _bars(open_, 78)
    cutoff = datetime(2026, 10, 26, 18, 10, tzinfo=UTC)  # 14:10 NY
    frames = frames_from_5m(bars, [(open_, close)], cutoff)
    four = frames["4h"]
    assert [b["start"] for b in four] == ["2026-10-26T13:30:00+00:00"]  # 13:30-16:00 NY still open
    assert four[0]["end"] == "2026-10-26T17:30:00+00:00" and four[0]["bars_5m"] == 48
    hours = frames["1h"]
    assert hours[0]["start"] == "2026-10-26T13:30:00+00:00" and hours[-1]["end"] <= cutoff.isoformat()
    assert all(b["start"] >= open_.isoformat() for f in frames.values() for b in f)


def test_early_close_ends_the_last_bucket_at_the_close():
    open_, close = datetime(2026, 11, 27, 14, 30, tzinfo=UTC), datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    bars = _bars(open_, 60)  # runs past the 13:00 NY close
    four = aggregate(bars, [(open_, close)], "4h", datetime(2026, 11, 28, tzinfo=UTC))
    assert len(four) == 1 and four[0]["end"] == "2026-11-27T18:00:00+00:00" and four[0]["bars_5m"] == 42
    hours = aggregate(bars, [(open_, close)], "1h", datetime(2026, 11, 28, tzinfo=UTC))
    assert hours[-1]["start"] == "2026-11-27T17:30:00+00:00" and hours[-1]["end"] == "2026-11-27T18:00:00+00:00"


def test_invalid_bars_are_dropped():
    open_, close = datetime(2026, 10, 26, 13, 30, tzinfo=UTC), datetime(2026, 10, 26, 20, 0, tzinfo=UTC)
    bad = [{"t": open_, "o": 10, "h": 9, "l": 11, "c": 10, "v": 1}, {"t": open_.replace(tzinfo=None), "o": 1,
                                                                        "h": 1, "l": 1, "c": 1, "v": 1}]
    assert aggregate(bad, [(open_, close)], "5m", close) == []
