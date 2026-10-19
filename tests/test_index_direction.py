"""CALL/PUT/WAIT research rules for SPX/NDX/SPY/QQQ are explicit and fail closed."""
from __future__ import annotations

import copy

from options_radar.index_direction import RULES_VERSION, build_index_direction

BULL = {
    "symbol": "SPY", "kind": "etf_proxy",
    "current_intraday_bar_confirmed": True,
    "last_finished_intraday_close": 772.0,
    "vwap_today": 769.0,
    "daily": {"bias": "UP"},
    "h1": {"bias": "UP", "ema_fast": 770.0, "atr14": 2.0},
    "m15": {"bias": "UP", "rsi14": 61.0, "atr14": 1.0},
    "levels": {
        "last_completed_session": {"high": 770.5, "low": 765.8},
        "previous_week": {"high": 779.4, "low": 760.6},
        "previous_month": {"high": 775.1, "low": 749.6},
    },
}


def _mirror(row):
    bear = copy.deepcopy(row)
    bear.update(last_finished_intraday_close=763.0, vwap_today=767.0)
    bear["daily"]["bias"] = "DOWN"
    bear["h1"]["bias"] = bear["m15"]["bias"] = "DOWN"
    bear["m15"]["rsi14"] = 39.0
    return bear


def test_aligned_breakout_above_prior_high_is_confirmed_call_with_level_targets():
    out = build_index_direction(BULL)
    assert out["version"] == RULES_VERSION
    assert (out["decision"], out["grade"]) == ("CALL", "CONFIRMED")
    assert out["targets"] == {"t1": 775.1, "t2": 779.4}
    assert out["invalidation"] == 768.5
    assert out["probability"] is None and out["execution_authority"] is False
    assert all(out["rules"]["CALL"].values())


def test_call_inside_prior_range_is_early_not_confirmed():
    row = {**BULL, "last_finished_intraday_close": 770.2}
    out = build_index_direction(row)
    assert (out["decision"], out["grade"]) == ("CALL", "EARLY")
    assert out["rules"]["CALL"]["R5_LEVEL_BREAK"] is False


def test_mirror_breakdown_is_confirmed_put():
    out = build_index_direction(_mirror(BULL))
    assert (out["decision"], out["grade"]) == ("PUT", "CONFIRMED")
    assert out["targets"]["t1"] == 760.6 and out["targets"]["t2"] == 749.6
    assert out["invalidation"] == 767.5


def test_stale_or_incomplete_intraday_always_waits():
    stale = build_index_direction({**BULL, "current_intraday_bar_confirmed": False})
    assert (stale["decision"], stale["reason_code"]) == ("WAIT", "DATA_STALE")
    missing = build_index_direction({**BULL, "m15": {"bias": "UP", "rsi14": None}})
    assert (missing["decision"], missing["reason_code"]) == ("WAIT", "DATA_INCOMPLETE")
    assert build_index_direction(None)["decision"] == "WAIT"


def test_daily_against_exhausted_or_misaligned_waits_and_logs_failed_rule():
    against = copy.deepcopy(BULL)
    against["daily"]["bias"] = "DOWN"
    out = build_index_direction(against)
    assert out["decision"] == "WAIT" and out["rules"]["CALL"]["R1_DAILY_NOT_AGAINST"] is False
    hot = copy.deepcopy(BULL)
    hot["m15"]["rsi14"] = 80.0
    assert build_index_direction(hot)["rules"]["CALL"]["R4_NOT_EXHAUSTED"] is False
    mixed = copy.deepcopy(BULL)
    mixed["m15"]["bias"] = "MIXED"
    assert build_index_direction(mixed)["decision"] == "WAIT"


def test_cash_index_without_vwap_uses_one_hour_ema_anchor():
    row = {**BULL, "symbol": "SPX", "kind": "index", "vwap_today": None}
    out = build_index_direction(row)
    assert out["rules"]["anchor_source"] == "EMA9_1H"
    assert out["anchor"] == 770.0
