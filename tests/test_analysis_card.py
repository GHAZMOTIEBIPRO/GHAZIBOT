from __future__ import annotations

from datetime import date, timedelta

from options_radar import analysis_card as ac
from options_radar import daily_plan as dp


def _daily(n=120, start=date(2026, 5, 1)):
    rows, p, d = [], 180.0, start
    while len(rows) < n:
        if d.weekday() < 5:
            o = p
            p = p * 1.002
            rows.append({"date": d.isoformat(), "open": round(o, 2), "high": round(max(o, p) + 1, 2),
                         "low": round(min(o, p) - 1, 2), "close": round(p, 2), "volume": 1000})
        d += timedelta(days=1)
    return rows


def _plan():
    rows = _daily()
    last = rows[-1]["date"]
    return dp.plan_for_symbol("NVDA", rows, last_closed_session=last, last_closed_week_end=last,
                              provider={"name": "alpaca_iex", "scope": "IEX only", "delay_note": "completed bars only"})


NEWS = [{"date": "2026-10-28", "title": "NVIDIA to Announce Results", "source_url": "https://investor.nvidia.com/n/1",
         "source": "Company IR", "kind": "IR_SCHEDULE"},
        {"date": "2026-10-27", "title": "no link", "source": "x"}]


def test_card_keeps_observed_interpretation_and_scenarios_apart_and_names_missing_frames():
    card = ac.build_card(_plan(), news=NEWS, options_status="SOURCE_TERMS_BLOCKED")
    assert card["asset_type"] == "STOCK" and ac.asset_type("SPY") == "ETF" and ac.asset_type("SPX") == "INDEX"
    assert card["source"] == "alpaca_iex" and card["feed_scope"] == "IEX only" and card["data_as_of"]
    assert all(lv["bar"] and lv["method"] for lv in card["observed"]["levels"])
    assert card["interpretation"]["frames"]["daily"]["trend"] == "UP"
    missing = {m["item"] for m in card["missing"]}
    assert {"1h", "4h", "15m", "5m", "options"} <= missing                  # no intraday bars were given
    assert [n["url"] for n in card["news"]] == ["https://investor.nvidia.com/n/1"]   # unlinked news dropped
    assert card["probability"] is None


def test_arabic_text_uses_only_card_numbers_and_an_invented_target_is_caught():
    card = ac.build_card(_plan(), news=NEWS)
    text = ac.explain_ar(card)
    ok, bad = ac.numbers_supported(text, card)
    assert ok, bad
    assert "ليس احتمالًا" in text and "لا يمكن تأكيد محفز الاختراق" in text and "investor.nvidia.com" in text
    rewrite = text + "\nالهدف القادم 215 بنسبة نجاح 72%"
    ok, bad = ac.numbers_supported(rewrite, card)
    assert not ok and set(bad) == {"215", "72"}


def test_unavailable_plan_gives_a_reason_not_a_reading():
    card = ac.build_card({"symbol": "AAPL", "available": False, "reason": "stale: last daily bar 2026-09-05"})
    assert card["available"] is False and "stale" in ac.explain_ar(card)
