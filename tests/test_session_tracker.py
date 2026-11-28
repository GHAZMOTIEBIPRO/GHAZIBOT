"""Intraday tracker: fixed levels, completed bars only, dated stages, honest ambiguity, slots."""
from datetime import datetime, timedelta, timezone

from options_radar import session_tracker as st
from scripts import run_session_tracker as rst

OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=timezone.utc)
MAP = {"symbol": "NVDA", "state": "CALL_WATCH", "prior_day": {"close": 105.0},
       "call": {"trigger": 110.0, "invalidation": 109.0,
                "targets": [{"name": "T1", "value": 112.0}, {"name": "T2", "value": 113.0}, {"name": "T3", "value": 114.0}]},
       "put": {"trigger": 100.0, "invalidation": 101.0, "targets": [{"name": "T1", "value": 99.0}]}}


def _bars(closes, vol=100):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append({"t": OPEN + timedelta(minutes=5 * i), "o": prev, "h": max(prev, c) + 0.05, "l": min(prev, c) - 0.05,
                    "c": c, "v": vol})
        prev = c
    return out


def test_stages_are_dated_and_ordered():
    closes = [105, 108, 110.5, 111, 111.2, 111.5, 112.2, 113.1, 113.5, 113.6, 114.2, 114.3]
    bars = _bars(closes)
    bars[2]["v"] = 1000  # the breakout bar carries 10 x its baseline volume
    out = st.track(MAP, bars, OPEN, {i: 100.0 for i in range(80)})
    stages = [e["stage"] for e in out["events"]]
    assert stages[0] == "EARLY_ALERT" and "CONFIRMED" in stages and stages.index("T1") < stages.index("T2") < stages.index("T3")
    assert out["events"][0]["at"] == (OPEN + timedelta(minutes=15)).isoformat()  # end of the 5m bar that closed above
    assert "INVALIDATED" not in stages and out["last_close"] == 114.3


def test_without_volume_it_is_only_a_breakout_watch_and_a_stop_ends_the_side():
    out = st.track(MAP, _bars([105, 110.5, 110.6, 108.5, 108.0, 108.0]), OPEN, {i: 1e9 for i in range(80)})
    stages = [e["stage"] for e in out["events"]]
    assert stages == ["BREAKOUT_WATCH", "INVALIDATED"]


def test_target_and_stop_in_one_bar_is_ambiguous():
    bars = _bars([105, 110.5, 110.6, 110.6])
    bars[3].update(h=112.5, l=108.5)
    stages = [e["stage"] for e in st.track(MAP, bars, OPEN)["events"]]
    assert stages[-1] == "AMBIGUOUS" and "T1" not in stages


def test_scorecard_counts_only_and_judges_watch_direction():
    tracked = {"NVDA": st.track(MAP, _bars([105, 110.5, 111, 112.3]), OPEN)}
    card = st.scorecard({"NVDA": MAP, "AMD": {"symbol": "AMD", "state": "NO_DATA"}}, tracked, {"NVDA": 112.3})
    assert card["maps"] == 1 and card["no_data"] == 1 and card["t1"] == 1 and card["watch_direction_right"] == 1
    assert all(isinstance(v, int) for v in card.values())


def test_session_slots_follow_open_and_close_including_early_close():
    close = OPEN + timedelta(hours=6, minutes=30)
    assert rst.session_slot(OPEN + timedelta(minutes=20), OPEN, close) is None  # first 15m not yet 16 min old
    assert rst.session_slot(OPEN + timedelta(minutes=35), OPEN, close) == "OPENING"
    assert rst.session_slot(OPEN + timedelta(hours=2), OPEN, close) == "INTRADAY"
    assert rst.session_slot(close - timedelta(minutes=55), OPEN, close) == "LASTHOUR"
    assert rst.session_slot(close + timedelta(minutes=30), OPEN, close) == "POSTCLOSE"
    early = OPEN + timedelta(hours=3, minutes=30)
    assert rst.session_slot(early - timedelta(minutes=50), OPEN, early) == "LASTHOUR"


def test_intraday_messages_only_carry_new_events_and_keys_hide_the_symbol():
    e = {"side": "CALL", "stage": "T1", "at": (OPEN + timedelta(minutes=40)).isoformat(), "level": 112.0}
    texts = rst.build_messages("INTRADAY", {"NVDA": MAP}, {}, [("NVDA", e)], OPEN + timedelta(hours=1), "2026-11-30", {})
    assert len(texts) == 1 and "الهدف الأول" in texts[0] and "ليست لحظية" in texts[0]
    assert rst.build_messages("INTRADAY", {"NVDA": MAP}, {}, [], OPEN, "2026-11-30", {}) == []
    key = rst.event_key("secret", "2026-11-30", "NVDA", e)
    assert len(key) == 16 and "NVDA" not in key and key != rst.event_key("other", "2026-11-30", "NVDA", e)
