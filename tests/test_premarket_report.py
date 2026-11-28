"""Pre-open price map, report slots and the owner-private report (no network)."""
import json
from datetime import date, datetime, timedelta, timezone

from options_radar import analysis_card as card_mod
from options_radar import daily_plan as dp
from options_radar import premarket_map as pm
from options_radar import premarket_report as report
from options_radar.telegram_ar import check_html
from scripts import build_daily_plan as bdp

UTC = timezone.utc


def _plan(symbol="NVDA", last_high=110.0, last_low=100.0, last_close=105.0, week_high=None):
    start = date(2026, 8, 3)
    rows, d, i = [], start, 0
    while len(rows) < 80:
        if d.weekday() < 5:
            p = 80 + i * 0.3
            rows.append({"date": d.isoformat(), "open": p, "high": p + 2, "low": p - 2, "close": p + 0.5, "volume": 1e6})
            i += 1
        d += timedelta(days=1)
    rows[-1].update(high=last_high, low=last_low, close=last_close, open=104.0)
    last = rows[-1]["date"]
    plan = dp.plan_for_symbol(symbol, rows, last_closed_session=last, last_closed_week_end=rows[-2]["date"],
                              provider={"name": "alpaca_sip", "scope": "SIP: all U.S. exchanges (consolidated tape)"})
    if week_high is not None:
        plan["prior_week"]["high"] = week_high
    plan["atr14"] = 4.0
    plan["quality_checks"] = {"daily": {"status": "OK", "issues": []}, "5m": {"status": "OK", "issues": []}}
    return plan


def _card(plan, trend=None):
    card = card_mod.build_card(plan)
    if trend:
        for frame in ("daily", "1h", "15m", "5m"):
            card["interpretation"]["frames"][frame] = {"trend": trend}
    return card


def test_targets_are_measured_ordered_spaced_and_named():
    plan = _plan(week_high=112.0)
    m = pm.build_map(_card(plan), plan)
    call, put = m["call"], m["put"]
    assert call["trigger"] == 110.0 and call["invalidation"] == 109.0  # high - 0.25 x ATR14
    assert [(t["name"], t["value"], t["method"]) for t in call["targets"]] == [
        ("T1", 112.0, "prior_week_high"), ("T2", 112.72, "ext_1272"), ("T3", 114.0, "atr_1")]
    assert put["trigger"] == 100.0 and put["invalidation"] == 101.0
    assert [t["value"] for t in put["targets"]] == sorted((t["value"] for t in put["targets"]), reverse=True)
    assert all(t["value"] < 100.0 - 0.1 * 4 for t in put["targets"])
    assert m["wait_band"] == {"low": 100.0, "high": 110.0} and m["pivot"] == round((110 + 100 + 105) / 3, 2)
    assert m["probability"] is None and m["execution_authority"] is False
    # same inputs -> same version; any changed level -> a new version
    assert pm.build_map(_card(plan), plan)["map_id"] == m["map_id"]
    other = _plan(last_high=111.0)
    assert pm.build_map(_card(other), other)["map_id"] != m["map_id"]


def test_state_needs_four_aligned_frames_and_clean_daily_bars():
    plan = _plan()
    assert pm.build_map(_card(plan, "UP"), plan)["state"] == "CALL_WATCH"
    assert pm.build_map(_card(plan, "DOWN"), plan)["state"] == "PUT_WATCH"
    mixed = _card(plan, "UP")
    mixed["interpretation"]["frames"]["5m"] = {"trend": "DOWN"}
    assert pm.build_map(mixed, plan)["state"] == "WAIT"
    # a 5m quality issue blocks the WATCH but keeps the daily levels
    bad_5m = _card(plan, "UP")
    bad_5m["data_quality"]["5m"] = {"status": "OK", "issues": ["GAP"]}
    m = pm.build_map(bad_5m, plan)
    assert m["state"] == "WAIT" and m["call"]["trigger"] == 110.0
    bad_daily = _card(plan, "UP")
    bad_daily["data_quality"]["daily"] = {"status": "DEGRADED", "issues": ["OHLC"]}
    assert pm.build_map(bad_daily, plan)["state"] == "NO_DATA"
    gone = {"symbol": "XYZ", "available": False, "reason": "stale: last daily bar 2026-09-05"}
    assert pm.build_map({}, gone) == {"schema": pm.SCHEMA, "symbol": "XYZ", "probability": None,
                                      "execution_authority": False, "state": "NO_DATA", "reason": gone["reason"]}


def test_premarket_reference_uses_only_completed_extended_hours_bars():
    prior_close = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)   # 13:00 New York early close
    opening = datetime(2026, 11, 30, 14, 30, tzinfo=UTC)
    usable = datetime(2026, 11, 30, 13, 50, tzinfo=UTC)
    bars = [{"t": prior_close - timedelta(minutes=5), "o": 1, "h": 1, "l": 1, "c": 99.0, "v": 1},  # regular session
            {"t": datetime(2026, 11, 30, 13, 30, tzinfo=UTC), "o": 106, "h": 107, "l": 105, "c": 106.5, "v": 10},
            {"t": datetime(2026, 11, 30, 13, 45, tzinfo=UTC), "o": 106, "h": 108, "l": 104, "c": 107.0, "v": 5},
            {"t": datetime(2026, 11, 30, 13, 50, tzinfo=UTC), "o": 107, "h": 109, "l": 107, "c": 108.0, "v": 5}]  # ends after usable
    ref = pm.premarket_reference(bars, session_open=opening, prior_close_at=prior_close, usable_until=usable)
    assert ref == {"price": 107.0, "bar_start": "2026-11-30T13:45:00+00:00", "high": 108.0, "low": 104.0,
                   "volume": 15.0, "bars": 2}
    assert pm.premarket_reference(bars[:1], session_open=opening, prior_close_at=prior_close, usable_until=usable) is None
    plan = _plan()
    m = pm.build_map(_card(plan), plan, premarket=ref)
    assert m["reference"]["type"] == "PREMARKET_LAST_COMPLETED_5M" and m["reference"]["gap_pct"] == round((107 / 105 - 1) * 100, 2)
    assert pm.build_map(_card(plan), plan)["reference"]["type"] == "PRIOR_SESSION_CLOSE"


def test_slots_follow_new_york_time_dst_late_and_holidays():
    # winter (EST): 08:35 New York = 13:35Z
    early = report.slot_for(datetime(2026, 11, 30, 13, 35, tzinfo=UTC), True)
    assert early["slot"] == "EARLY" and early["late"] is False and early["due_at"] == "2026-11-30T08:30:00-05:00"
    late = report.slot_for(datetime(2026, 11, 30, 13, 45, tzinfo=UTC), True)
    assert late["late"] is True and late["late_minutes"] == 15
    assert report.slot_for(datetime(2026, 11, 30, 14, 2, tzinfo=UTC), True)["slot"] == "FINAL"
    assert report.slot_for(datetime(2026, 11, 30, 14, 31, tzinfo=UTC), True) is None  # after the open
    assert report.slot_for(datetime(2026, 11, 30, 11, 47, tzinfo=UTC), True) is None  # 06:47: too early
    # summer (EDT): 08:35 New York = 12:35Z
    assert report.slot_for(datetime(2026, 6, 1, 12, 35, tzinfo=UTC), True)["slot"] == "EARLY"
    assert report.slot_for(datetime(2026, 11, 26, 13, 35, tzinfo=UTC), False) is None  # Thanksgiving
    assert report.missed_slots(datetime(2026, 11, 30, 14, 5, tzinfo=UTC), True, set()) == ["EARLY"]
    assert report.missed_slots(datetime(2026, 11, 30, 14, 5, tzinfo=UTC), True, {"EARLY"}) == []


def _maps():
    plan = _plan("NVDA", week_high=112.0)
    maps = {"SPY": pm.build_map(_card(_plan("SPY")), _plan("SPY")),
            "QQQ": {"schema": pm.SCHEMA, "symbol": "QQQ", "state": "NO_DATA", "reason": "provider refused"},
            "NVDA": pm.build_map(_card(plan, "UP"), plan),
            "AMD": pm.build_map(_card(_plan("AMD")), _plan("AMD"))}
    return maps


def test_render_lists_every_symbol_and_keeps_messages_valid():
    maps = _maps()
    slot = report.slot_for(datetime(2026, 11, 30, 13, 45, tzinfo=UTC), True)
    details = pm.rank_details(maps, pinned=("SPY", "QQQ"))
    assert details == ["SPY", "NVDA"]  # QQQ has no data; AMD is WAIT and never forced in
    texts = report.render(maps, slot=slot, now=datetime(2026, 11, 30, 13, 45, tzinfo=UTC), session_date="2026-11-30",
                          index_funds=("SPY", "QQQ"), detail_symbols=details, fetched=3, attempted=4)
    joined = "\n".join(texts)
    for symbol in maps:
        assert f"<b>{symbol}</b>" in joined
    assert "متأخر 15 دقيقة" in texts[0] and "SPX / NDX: غير متاح" in texts[0] and "provider refused" in joined
    assert "T1 112.00 (قمة الأسبوع السابق)" in joined and "إبطال 109.00" in joined
    assert "مراقبة CALL" in joined and "احتمال نجاح" in joined
    for text in texts:
        assert len(text) <= report.MAX_CHARS
        check_html(text)


def test_rows_and_cards_only_print_numbers_from_their_map():
    """Computed once: the text holds no number that the map does not hold (bar the method constants)."""
    method = {127.2, 161.8, 14.0, 4.0, 15.0, 1.0}
    for m in _maps().values():
        for text in (report.row(m), *( [report.card(m)] if m["state"] != "NO_DATA" else [])):
            ok, bad = card_mod.numbers_supported(text, {**m, "method": sorted(method)})
            assert ok, (m["symbol"], bad)


def test_render_splits_long_summaries_between_rows_only():
    maps = {f"S{i:02d}": pm.build_map(_card(_plan(f"S{i:02d}")), _plan(f"S{i:02d}")) for i in range(60)}
    slot = report.slot_for(datetime(2026, 11, 30, 13, 35, tzinfo=UTC), True)
    texts = report.render(maps, slot=slot, now=datetime(2026, 11, 30, 13, 35, tzinfo=UTC), session_date="2026-11-30",
                          index_funds=(), detail_symbols=[], fetched=60, attempted=60)
    assert len(texts) >= 2 and all(len(t) <= report.MAX_CHARS for t in texts)
    assert all(f"<b>S{i:02d}</b>" in "\n".join(texts) for i in range(60))
    assert "(تابع)" in texts[1]


class _Receipt:
    message_id = 7


def _private():
    plans = {s: _plan(s) for s in ("SPY", "NVDA")}
    plans["NVDA"]["premarket"] = None
    cards = {s: _card(p, "UP" if s == "NVDA" else None) for s, p in plans.items()}
    return {"enabled": True, "reason": "OWNER_AUTHORIZED_INTERNAL_USE", "plans": plans, "cards": cards,
            "fetch_status": {s: {"daily": "OK", "feeds": ["sip"]} for s in plans}}


def _facts(day="2026-11-30"):
    return {"today_is_session": True, "today": {"date": day}, "last_closed_session": "2026-11-27"}


ENV = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true", "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true",
       "TELEGRAM_OWNER_CHAT_ID": "42"}


def test_report_slot_sends_once_records_status_only_and_never_sends_outside_windows(tmp_path):
    sent = []

    def send(text, chat):
        sent.append((chat, text))
        return _Receipt()

    def run(now):
        return bdp.run_report_slot(_private(), _facts(), now, tmp_path, env=ENV,
                                   get_chat=lambda _: {"type": "private"}, send=send)

    assert run(datetime(2026, 11, 30, 12, 0, tzinfo=UTC)) is None and sent == []  # 07:00 New York
    first = run(datetime(2026, 11, 30, 13, 33, tzinfo=UTC))
    assert first["slot"] == "EARLY" and first["status"] == "DELIVERED" and first["late"] is False
    count = len(sent)
    assert count >= 2 and {c for c, _ in sent} == {"42"}  # summary + detailed cards, owner chat only
    again = run(datetime(2026, 11, 30, 13, 40, tzinfo=UTC))
    assert again["status"] == "DELIVERED" and len(sent) == count  # deduplicated
    marker_text = (tmp_path / "report_EARLY.json").read_text()
    marker = json.loads(marker_text)
    assert marker["accepted"] == marker["messages"] == count and marker["telegram_acceptance_is_not_read_receipt"]
    assert "fingerprints" in marker and marker["fingerprints"] is None  # no independent state key, no fingerprints
    # the public marker carries no level, price or state derived from the private bars
    assert "trigger" not in marker_text and "WATCH" not in marker_text and "105" not in marker_text.replace(
        "2026-11-30", "")
    floats = [v for v in json.loads(marker_text).values() if isinstance(v, float)]
    assert floats == []
    final = run(datetime(2026, 11, 30, 14, 12, tzinfo=UTC))  # 09:12: FINAL, 12 minutes late
    assert final["slot"] == "FINAL" and final["late"] is True and final["late_minutes"] == 12
    assert run(datetime(2026, 11, 30, 15, 0, tzinfo=UTC)) is None  # after the open: nothing sent


def test_missed_slot_is_recorded_and_never_sent_late(tmp_path):
    sent = []
    out = bdp.run_report_slot(_private(), _facts(), datetime(2026, 11, 30, 14, 3, tzinfo=UTC), tmp_path, env=ENV,
                              get_chat=lambda _: {"type": "private"},
                              send=lambda text, chat: sent.append(text) or _Receipt())
    assert out["slot"] == "FINAL"
    missed = json.loads((tmp_path / "report_EARLY.json").read_text())
    assert missed["status"] == "MISSED" and missed["late"] is True
    assert all("التقرير المبكر" not in t for t in sent)


def test_failed_send_is_retried_in_the_window_but_bounded(tmp_path):
    def boom(text, chat):
        raise RuntimeError("network")

    for minute in (31, 36, 41, 46):
        out = bdp.run_report_slot(_private(), _facts(), datetime(2026, 11, 30, 13, minute, tzinfo=UTC), tmp_path,
                                  env=ENV, get_chat=lambda _: {"type": "private"}, send=boom)
    assert out["status"] == "SEND_FAILED" and out["attempt"] == bdp.MAX_SLOT_ATTEMPTS


def _run(tmp_path, minute, send, hour=13, album=None, env=None, private=None):
    return bdp.run_report_slot(private or _private(), _facts(), datetime(2026, 11, 30, hour, minute, tzinfo=UTC),
                               tmp_path, env=env or ENV, get_chat=lambda _: {"type": "private"}, send=send,
                               send_album=album)


def test_partial_delivery_resends_only_the_undelivered_items(tmp_path):
    sent, broken = [], [True]

    def flaky(text, chat):
        sent.append(text)
        if broken[0] and len(sent) > 1:
            raise RuntimeError("telegram 400")
        return _Receipt()

    first = _run(tmp_path, 31, flaky)
    assert first["status"] == "PARTIAL" and first["accepted"] == 1 and first["messages"] >= 2
    delivered = [k for k, v in first["items"].items() if v["status"] == "DELIVERED"]
    broken[0] = False
    again = _run(tmp_path, 36, flaky)
    assert again["status"] == "DELIVERED"
    # the item already accepted was not sent again
    assert len(sent) == 2 * first["messages"] - 1 and delivered == [k for k in first["items"] if k.endswith(":text:0")]


def test_unconfirmed_item_is_never_resent_automatically(tmp_path):
    import requests

    calls = []

    def timeout(text, chat):
        calls.append(text)
        if len(calls) == 1:
            raise requests.ReadTimeout("read timed out")
        return _Receipt()

    first = _run(tmp_path, 31, timeout)
    assert first["items"][next(iter(first["items"]))]["status"] == "UNCONFIRMED"
    assert first["status"] == "UNCONFIRMED"
    assert _run(tmp_path, 36, timeout)["status"] == "UNCONFIRMED" and len(calls) == first["messages"]


def test_interrupted_run_leaves_a_record_per_message(tmp_path):
    sent = []

    def dies(text, chat):
        if sent:
            raise SystemExit("runner cancelled")  # not caught by the policy layer
        sent.append(text)
        return _Receipt()

    try:
        _run(tmp_path, 31, dies)
    except SystemExit:
        pass
    marker = json.loads((tmp_path / "report_EARLY.json").read_text())
    assert [v["status"] for v in marker["items"].values()] == ["DELIVERED"]
    resumed = _run(tmp_path, 36, lambda text, chat: sent.append(text) or _Receipt())
    assert resumed["status"] == "DELIVERED" and len(sent) == resumed["messages"]  # first one not repeated


def test_ids_are_unique_per_session_slot_and_message(tmp_path):
    out = _run(tmp_path, 31, lambda t, c: _Receipt())
    assert all(k.startswith("2026-11-30:EARLY:text:") for k in out["items"])
    assert len(set(out["items"])) == out["messages"] == out["text_messages"]


def test_final_sends_cards_only_for_changed_symbols(tmp_path):
    env = {**ENV, "GHAZI_STATE_HMAC_KEY": "s" * 32}
    _run(tmp_path, 31, lambda t, c: _Receipt(), env=env)
    texts = []
    final = _run(tmp_path, 2, lambda t, c: texts.append(t) or _Receipt(), hour=14, env=env)
    assert final["slot"] == "FINAL" and final["status"] == "DELIVERED"
    joined = "\n".join(texts)
    assert "لا تغيير جوهري" in joined and "تنبيه مبكر: إغلاق 5د" not in joined  # no unchanged cards
    early = json.loads((tmp_path / "report_EARLY.json").read_text())["fingerprints"]
    assert set(early) == {"key_id", "nonce", "tags"} and len(early["tags"]) == 256  # sealed: no symbol keys
    assert not any(sym in json.dumps(early) for sym in ("NVDA", "QQQ", "AAPL"))
    changed = _private()
    changed["plans"]["NVDA"]["prior_session"]["high"] = 111.0
    texts.clear()
    (tmp_path / "report_FINAL.json").unlink()
    _run(tmp_path, 3, lambda t, c: texts.append(t) or _Receipt(), hour=14, env=env, private=changed)
    assert "<b>NVDA</b>" in "\n".join(texts) and ": 1." in "\n".join(texts)


def test_charts_go_out_as_albums_after_the_text(tmp_path):
    albums = []
    out = _run(tmp_path, 31, lambda t, c: _Receipt(), album=lambda a, c: albums.append(a) or _Receipt())
    assert out["charts"] == "OK" and out["status"] == "DELIVERED"
    assert [k.split(":")[2] for k in out["items"]][-1] == "charts" and len(albums) == 1
    png, caption = albums[0][0]
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(caption) <= 1024 and "سيناريو CALL" in caption


def test_every_planned_symbol_gets_a_map_row_even_when_not_fetched():
    maps = bdp.maps_for(_private())
    assert list(maps) == list(bdp.PLAN_SYMBOLS)
    assert maps["MSFT"]["state"] == "NO_DATA" and "time budget" in maps["MSFT"]["reason"]
    assert maps["NVDA"]["state"] == "CALL_WATCH"


def test_every_chart_level_is_printed_in_the_card_text():
    """Text and image come from one map: each line drawn on the chart carries the same number in the card."""
    from options_radar import price_map_chart as chart

    plan = _plan("NVDA", week_high=112.0)
    plan["recent_daily"] = [{"date": f"2026-11-{d:02d}", "open": 99.0, "high": 115.0 - d * 0.1, "low": 90.0 + d * 0.1,
                             "close": 100.0} for d in range(1, 21)]
    m = pm.build_map(_card(plan, "UP"), plan)
    text = report.card(m)
    assert m["levels_sr"]  # support and resistance exist for this plan
    for level in chart.levels(m):
        assert f"{level['value']:,.2f}" in text, level


def test_default_charts_are_index_funds_and_three_leaders():
    maps = {s: pm.build_map(_card(_plan(s), "UP" if s in ("NVDA", "AMD") else None), _plan(s))
            for s in ("SPY", "QQQ", "NVDA", "AMD", "MSFT", "META", "AAPL")}
    chosen = bdp.chart_symbols(maps)
    assert chosen[:2] == ["SPY", "QQQ"] and len(chosen) == 5 and chosen[2:4] == ["AMD", "NVDA"]




def test_leadership_uses_relative_strength_and_says_it_is_not_index_weight():
    maps = {s: {"symbol": s, "state": "WAIT", "prior_change_pct": c}
            for s, c in (("QQQ", 1.0), ("NVDA", 3.2), ("AMD", 2.1), ("MSFT", 0.4), ("META", -1.5), ("AAPL", 0.9))}
    lines = report.leadership(maps)
    text = "\n".join(lines)
    assert "NVDA +3.20%" in text.split("الأضعف")[0] and "META -1.50%" in text.split("الأضعف")[1]
    assert "عكس اتجاه السوق: META" in text and "لا أوزان مؤشر" in text
    assert report.leadership({"NVDA": maps["NVDA"]}) == []  # no benchmark, no claim
