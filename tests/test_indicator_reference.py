"""Indicators checked against independent implementations and hand-computed values."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from options_radar import daily_plan as dp
from options_radar.bar_aggregation import aggregate


def test_ema_matches_pandas_and_a_hand_computed_case():
    assert dp.ema([1.0, 2.0, 3.0], 3) == [1.0, 1.5, 2.25]  # k = 2/(3+1) = 0.5
    rng = np.random.default_rng(3)
    closes = list(100 + np.cumsum(rng.normal(0, 1, 300)))
    ours = dp.ema(closes, 20)
    ref = pd.Series(closes).ewm(span=20, adjust=False).mean().tolist()
    assert np.allclose(ours, ref, rtol=0, atol=1e-9)


def test_wilder_atr_matches_an_independent_pandas_version_and_hand_case():
    bars = [{"high": 10, "low": 8, "close": 9}, {"high": 11, "low": 9, "close": 10},
            {"high": 12, "low": 9, "close": 11}, {"high": 11, "low": 10, "close": 10.5}]
    # TR = [2 (11-9 vs |11-9|,|9-9|), 3 (12-9), 1 (11-10)]; period 2: seed (2+3)/2=2.5, then (2.5*1+1)/2 = 1.75
    assert dp.atr(bars, period=2) == 1.75
    rng = np.random.default_rng(4)
    close = 100 + np.cumsum(rng.normal(0, 1, 200))
    high, low = close + rng.uniform(0.1, 1, 200), close - rng.uniform(0.1, 1, 200)
    frame = pd.DataFrame({"high": high, "low": low, "close": close})
    prev = frame["close"].shift(1)
    tr = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev).abs(), (frame["low"] - prev).abs()],
                   axis=1).max(axis=1).iloc[1:].to_numpy()
    ref = tr[:14].mean()
    for value in tr[14:]:
        ref = (ref * 13 + value) / 14
    ours = dp.atr(frame.to_dict("records"), 14)
    assert abs(ours - ref) < 1e-9


def test_partial_four_hour_bucket_is_labelled_with_its_real_length():
    utc = timezone.utc
    open_, close = datetime(2026, 10, 23, 13, 30, tzinfo=utc), datetime(2026, 10, 23, 20, 0, tzinfo=utc)
    bars = [{"t": open_ + timedelta(minutes=5 * i), "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0, "v": 1} for i in range(78)]
    four = aggregate(bars, [(open_, close)], "4h", close)
    assert [(b["minutes"], b["partial"]) for b in four] == [(240, False), (150, True)]


def test_short_history_says_what_is_missing():
    bars = [{"date": f"2026-10-{d:02d}", "open": 1, "high": 2, "low": 0.5, "close": 1 + d / 100} for d in range(1, 11)]
    trend = dp.frame_trend(bars)
    assert trend["trend"] == "INSUFFICIENT" and trend["reason"] == "needs 22 completed bars for EMA20 and its slope, has 10"
    assert dp.REQUIREMENTS["daily"]["slow_from"] == 50 and dp.REQUIREMENTS["weekly"]["trend_bars"] == 12
