"""Daily plan engine on synthetic fixture bars (test data, not market data)."""
from datetime import date, timedelta
from itertools import pairwise

import pytest

from options_radar import daily_plan as dp

PROVIDER = {"name": "fixture", "scope": "TEST_FIXTURE", "delay_note": "test", "volume_scope": "test"}


def sessions(n, start=date(2026, 7, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def bars(n, start_price=100.0, step=0.5):
    out, price = [], start_price
    for i, day in enumerate(sessions(n)):
        o = price
        c = price + step
        out.append({"date": day, "open": o, "high": max(o, c) + 0.4, "low": min(o, c) - 0.4, "close": c,
                    "volume": 1000 + i})
        price = c
    return out


def test_uptrend_frames_levels_and_conditional_scenarios():
    daily = bars(60)
    last = daily[-1]["date"]
    plan = dp.plan_for_symbol("TEST", daily, last_closed_session=last, last_closed_week_end=last, provider=PROVIDER)
    assert plan["available"] is True and plan["frames"]["daily"]["trend"] == "UP"
    assert plan["frames"]["daily"]["structure"] == "HIGHER_HIGHS_LOWS"
    assert plan["frames"]["weekly"]["trend"] in ("UP", "INSUFFICIENT")
    for name in ("4h", "1h", "15m", "5m"):
        assert plan["frames"][name]["trend"] == "UNAVAILABLE"
    assert plan["prior_session"]["date"] == last and plan["prior_session"]["change_pct"] > 0
    bull = next(s for s in plan["scenarios"] if s["kind"] == "BULLISH")
    assert bull["trigger_level"] == daily[-1]["high"]
    assert bull["invalidation"] == pytest.approx(daily[-1]["high"] - 0.25 * plan["atr14"], abs=1e-3)
    assert plan["probability"] is None and plan["execution_authority"] is False
    assert plan["frames_available"] == ["weekly", "daily"] or plan["frames_available"] == ["daily"]


def test_unclosed_session_and_week_are_excluded_and_bad_bars_dropped():
    daily = bars(30)
    unfinished = daily[-1]["date"]
    daily.append({"date": "2026-08-20", "open": 1, "high": 0.5, "low": 2, "close": 1})  # impossible bar
    plan = dp.plan_for_symbol("TEST", daily, last_closed_session=daily[-3]["date"],
                              last_closed_week_end=daily[-8]["date"], provider=PROVIDER)
    assert plan["last_closed_session"] == daily[-3]["date"] != unfinished
    weekly = dp.weekly_from_daily(dp.completed_daily(daily, last_closed_session=daily[-3]["date"]),
                                  last_closed_week_end=daily[-8]["date"])
    assert all(w["end"] <= daily[-8]["date"] for w in weekly)


def test_insufficient_history_and_downtrend():
    short = bars(10)
    plan = dp.plan_for_symbol("TEST", short, last_closed_session=short[-1]["date"],
                              last_closed_week_end=short[-1]["date"], provider=PROVIDER)
    assert plan["frames"]["daily"]["trend"] == "INSUFFICIENT" and plan["atr14"] is None and plan["scenarios"] == []
    down = bars(60, 200, -0.5)
    plan = dp.plan_for_symbol("TEST", down, last_closed_session=down[-1]["date"],
                              last_closed_week_end=down[-1]["date"], provider=PROVIDER)
    assert plan["frames"]["daily"]["trend"] == "DOWN"
    assert dp.plan_for_symbol("X", [], last_closed_session="2026-10-23", last_closed_week_end="2026-10-23",
                              provider=PROVIDER)["available"] is False


def test_atr_matches_hand_computation():
    rows = [{"date": f"d{i}", "open": 10, "high": 11 + (i % 2), "low": 9, "close": 10} for i in range(16)]
    trs = [max(r["high"] - r["low"], abs(r["high"] - p["close"]), abs(r["low"] - p["close"])) for p, r in pairwise(rows)]
    first = sum(trs[:14]) / 14
    expected = (first * 13 + trs[14]) / 14
    assert dp.atr(rows) == pytest.approx(expected)
