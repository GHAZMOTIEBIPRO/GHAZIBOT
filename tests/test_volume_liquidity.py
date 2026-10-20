"""Volume & liquidity context: exact definitions, completed bars, inference labels."""
from __future__ import annotations

import pandas as pd

from options_radar.volume_liquidity import (
    _sessions,
    liquidity_context,
    read_ar,
    same_time_rvol,
    volume_profile,
)

NY = "America/New_York"


def _session(day: str, closes, volumes, *, end: str = "16:00"):
    index = pd.date_range(f"{day} 09:30", f"{day} {end}", freq="15min", tz=NY, inclusive="left")
    index = index[: len(closes)]
    closes = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame({"Open": closes.shift(1).fillna(closes.iloc[0]), "High": closes + 0.5,
                         "Low": closes - 0.5, "Close": closes, "Volume": volumes[: len(index)]},
                        index=index)


def _daily(rows):
    days = pd.DatetimeIndex([d for d, *_ in rows]).tz_localize(NY)
    return pd.DataFrame([{"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1}
                         for _, o, h, lo, c in rows], index=days)


def test_volume_profile_puts_poc_where_volume_concentrates():
    bars = pd.DataFrame({"High": [101, 101, 105, 110], "Low": [100, 100, 104, 109],
                         "Volume": [1000, 1000, 10, 10], "Close": [100.5, 100.5, 104.5, 109.5]},
                        index=pd.date_range("2026-10-20 09:30", periods=4, freq="15min", tz=NY))
    prof = volume_profile(bars, bins=10)
    assert prof["method"] == "OHLCV_UNIFORM_RANGE_ESTIMATE"
    assert 100 <= prof["poc"] <= 101
    assert prof["val"] <= prof["poc"] <= prof["vah"] and prof["vah"] <= 102
    assert volume_profile(bars.assign(Volume=0)) is None


def test_rvol_compares_same_time_of_day_not_full_day():
    prior = [_session(d, [100] * 26, [1000] * 26) for d in ("2026-10-13", "2026-10-14", "2026-10-15")]
    today = _session("2026-10-16", [100] * 4, [3000] * 4)  # 4 completed bars by 10:30
    rv = same_time_rvol([*prior, today])
    assert rv["rvol"] == 3.0 and rv["state"] == "HIGH"
    assert "median of 3 prior sessions" in rv["basis"]
    assert same_time_rvol([prior[0], today]) is None  # too few comparable sessions


def test_breakout_with_volume_is_confirmed_and_a_failed_one_is_named():
    prior = [_session(d, [100] * 26, [1000] * 26) for d in ("2026-10-13", "2026-10-14", "2026-10-15")]
    daily = _daily([("2026-10-15", 99, 102, 98, 100)])
    good = _session("2026-10-16", [100, 101, 103, 104], [1000, 1000, 4000, 1000])
    ctx = liquidity_context(daily, pd.concat([*prior, good]))
    assert ctx["breakout"] == "BREAKOUT_VOLUME_CONFIRMED"
    assert ctx["opening_range"]["status"] == "ABOVE"
    assert ctx["gap_pct"] == 0.0 and ctx["inference_only"] is True
    weak = _session("2026-10-16", [100, 101, 103, 104], [1000] * 4)
    assert liquidity_context(daily, pd.concat([*prior, weak]))["breakout"] == "BREAKOUT_VOLUME_UNCONFIRMED"
    failed = _session("2026-10-16", [100, 103, 101.5, 101], [1000] * 4)
    ctx = liquidity_context(daily, pd.concat([*prior, failed]))
    assert ctx["breakout"] == "FAILED_BREAKOUT"
    assert ctx["sweep_proxy"] is None  # closed above first: a failed breakout, not a one-bar sweep
    swept = _session("2026-10-16", [100, 101.5, 101], [1000] * 3)
    swept.iloc[1, swept.columns.get_loc("High")] = 103.0  # pierced 102, closed back below
    ctx = liquidity_context(daily, pd.concat([*prior, swept]))
    assert ctx["sweep_proxy"] == "ABOVE_PRIOR_HIGH_REJECTED" and ctx["breakout"] is None


def test_insufficient_bars_fail_closed_and_reading_never_claims_order_flow():
    assert liquidity_context(pd.DataFrame(), pd.DataFrame())["status"] == "INSUFFICIENT_BARS"
    assert _sessions(pd.DataFrame({"Close": [1.0]})) == []
    prior = [_session(d, [100] * 26, [1000] * 26) for d in ("2026-10-13", "2026-10-14", "2026-10-15")]
    daily = _daily([("2026-10-15", 99, 102, 98, 100)])
    lines = read_ar(liquidity_context(daily, pd.concat([*prior, _session("2026-10-16", [100] * 4, [500] * 4)])))
    text = " ".join(lines)
    assert "منخفض" in text and "دفتر الأوامر" in text
    assert "تجميع مؤسسي" not in text and "مؤكد" not in text
