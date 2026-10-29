from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from options_radar import daily_plan as dp
from options_radar import ohlcv_quality as q

T0 = datetime(2026, 10, 28, 13, 30, tzinfo=timezone.utc)   # 09:30 New York


def bar(i, o=100.0, h=101.0, low=99.0, c=100.5, v=1000, start=None):
    return {"t": (start or T0 + timedelta(minutes=5 * i)).isoformat(), "open": o, "high": h, "low": low, "close": c,
            "volume": v}


def codes(report):
    return {i["code"]: i["rows"] for i in report["issues"]}


def test_each_row_rule_has_its_own_code_and_bad_rows_are_dropped_not_hidden():
    rows = [bar(0), bar(1, h=99.5), bar(2, low=100.8), bar(3, o=-1, low=-2), bar(4, v=-5), bar(5, c=None), bar(6)]
    r = q.check_bars(rows, interval="5m", as_of=T0 + timedelta(hours=2), need=1)
    assert r["status"] == "DATA_ERROR"
    assert codes(r) == {"HIGH_BELOW_BODY": 1, "LOW_ABOVE_BODY": 1, "NON_POSITIVE_PRICE": 1, "NEGATIVE_VOLUME": 1,
                        "NON_FINITE_PRICE": 1}
    assert r["completed"] == 2 and [x["t"] for x in r["clean"]] == [T0, T0 + timedelta(minutes=30)]


def test_pandera_and_plain_python_give_the_same_codes(monkeypatch):
    pytest.importorskip("pandera")
    rows = [bar(0), bar(1, h=99.5), bar(2, v=-1), bar(3, o=0, low=0)]
    with_pandera = q.check_bars(rows, interval="5m", as_of=T0 + timedelta(hours=1))
    assert with_pandera["engine"] == "pandera"
    monkeypatch.setattr(q, "OHLCV_SCHEMA", None)
    plain = q.check_bars(rows, interval="5m", as_of=T0 + timedelta(hours=1))
    assert plain["engine"] == "python" and codes(plain) == codes(with_pandera)


def test_order_duplicates_and_time_zones():
    rows = [bar(2), bar(0), bar(1), bar(1, c=100.7), {**bar(3), "t": "2026-10-28T13:45:00"}]
    r = q.check_bars(rows, interval="5m", as_of=T0 + timedelta(hours=1))
    c = codes(r)
    assert c["OUT_OF_ORDER"] >= 1 and c["DUPLICATE_TIMESTAMP"] == 1 and c["NAIVE_TIMESTAMP"] == 1
    assert [x["t"] for x in r["clean"]] == [T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=10)]
    assert r["clean"][1]["close"] == 100.7                     # the later copy of a duplicate is kept


def test_a_forming_bar_never_counts_as_completed():
    rows = [bar(i) for i in range(4)]
    as_of = T0 + timedelta(minutes=17)                           # bar 3 (13:45-13:50) is still forming
    r = q.check_bars(rows, interval="5m", as_of=as_of)
    assert r["completed"] == 3 and r["forming"] == 1
    closes = {"2026-10-27": datetime(2026, 10, 27, 20, tzinfo=timezone.utc),
              "2026-10-28": datetime(2026, 10, 28, 20, tzinfo=timezone.utc)}
    daily = [bar(0, start=datetime(2026, 10, 27, tzinfo=timezone.utc)), bar(0, start=datetime(2026, 10, 28, tzinfo=timezone.utc))]
    mid_session = q.check_bars(daily, interval="1d", as_of=datetime(2026, 10, 28, 18, tzinfo=timezone.utc),
                               session_close=closes.get)
    assert mid_session["completed"] == 1 and mid_session["forming"] == 1   # today is not "yesterday"


def test_split_jump_is_flagged_on_unadjusted_data_only():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [bar(0, start=start, o=200, h=202, low=198, c=200),
            bar(0, start=start + timedelta(days=1), o=100.5, h=101, low=99, c=100)]
    closes = {f"2026-10-0{d}": datetime(2026, 10, d, 20, tzinfo=timezone.utc) for d in (1, 2)}
    raw = q.check_bars(rows, interval="1d", as_of=datetime(2026, 10, 3, tzinfo=timezone.utc),
                       adjustment="raw", session_close=closes.get)
    assert raw["split_suspects"][0]["near_ratio"] == "1:2"
    adjusted = q.check_bars(rows, interval="1d", as_of=datetime(2026, 10, 3, tzinfo=timezone.utc),
                            adjustment="split", session_close=closes.get)
    assert adjusted["split_suspects"] == []


def test_the_four_outcomes_stay_apart():
    as_of = T0 + timedelta(hours=1)
    assert q.check_bars(None, interval="5m", as_of=as_of, fetch_status="CREDENTIALS_MISSING")["status"] == "SOURCE_UNAVAILABLE"
    assert q.check_bars([], interval="5m", as_of=as_of)["status"] == "SOURCE_UNAVAILABLE"
    short = q.check_bars([bar(i) for i in range(5)], interval="5m", as_of=as_of, need=50)
    assert short["status"] == "INSUFFICIENT_HISTORY" and short["history"] == {"have": 5, "need": 50, "sufficient": False}
    assert q.check_bars([bar(i) for i in range(5)], interval="5m", as_of=as_of, need=5)["status"] == "OK"
    assert "clean" not in q.summary(short)


def _series(n=300, seed=7):
    random.seed(seed)
    bars, p = [], 100.0
    for _ in range(n):
        o = p
        p = max(1.0, p * (1 + random.gauss(0, 0.015)))
        bars.append({"open": o, "high": max(o, p) * (1 + abs(random.gauss(0, 0.005))),
                     "low": min(o, p) * (1 - abs(random.gauss(0, 0.005))), "close": p})
    return bars


def test_ema_and_atr_match_the_reference_library_with_the_same_settings():
    ta = pytest.importorskip("pandas_ta_classic")
    bars = _series()
    closes = pd.Series([b["close"] for b in bars])
    ours = dp.ema(closes.tolist(), 20)
    # same seeding (first value, no SMA warm-up): identical
    assert max(abs(a - b) for a, b in zip(ours, ta.ema(closes, length=20, sma=False))) < 1e-9
    # the library's default seeds with an SMA: different early, converged after the declared warm-up
    default = ta.ema(closes, length=20)
    assert max(abs(a - b) for a, b in zip(ours[100:], default[100:])) < 1e-3
    df = pd.DataFrame(bars)
    ref_atr = float(ta.atr(df["high"], df["low"], df["close"], length=14, mamode="rma").iloc[-1])
    assert abs(dp.atr(bars, 14) - ref_atr) < 1e-9
