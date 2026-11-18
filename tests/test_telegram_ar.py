from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from options_radar import telegram_ar as ar


def test_lines_starting_with_latin_or_symbols_become_right_to_left():
    text = ar.render(["<b>NVDA</b> — مراقبة", "• <b>MRK</b>\u200e — حدث", "🛰️ تقرير", "202.10 ← 203.15"])
    lines = text.split("\n")
    assert lines[0].startswith(ar.RLM)          # Latin first
    assert lines[1].startswith(ar.RLM)          # bullet then Latin
    assert not lines[2].startswith(ar.RLM)      # emoji is neutral, first strong char is Arabic
    assert lines[3].startswith(ar.RLM)          # numbers only


def test_arabic_dates_times_and_plurals():
    moment = datetime(2026, 11, 18, 15, 5, tzinfo=timezone.utc)
    assert ar.date_ar(moment) == "الأربعاء 18 نوفمبر 2026"
    assert ar.date_ar("2026-11-17", year=False) == "الثلاثاء 17 نوفمبر"
    assert ar.when_ar(moment) == "10:05 ص نيويورك (6:05 م الرياض)"
    assert [ar.days_ar(n) for n in (1, 2, 5, 12)] == ["يوم واحد", "يومين", "5 أيام", "12 يومًا"]
    assert [ar.stocks_ar(n) for n in (1, 2, 8, 60)] == ["سهم واحد", "سهمين", "8 أسهم", "60 سهمًا"]


def test_every_event_kind_has_arabic_words_and_unknown_kinds_hide_codes():
    for kind, (name, why, watch) in ar.EVENT_KINDS.items():
        assert ar.first_strong(name) == "R" and why and watch, kind
    assert "_" not in ar.event_kind("SOMETHING_NEW")[0]


def test_render_refuses_messages_over_the_telegram_limit():
    with pytest.raises(ValueError):
        ar.render(["ا" * 5000])


def test_only_balanced_telegram_tags_are_accepted():
    ar.check_html('<b>نص</b> <a href="https://example.com">رابط</a>')
    for bad in ("<b>نص <b>NVDA</b></b>", "<ul><li>x</li></ul>", "سطر<br>سطر", "<b>غير مغلق"):
        with pytest.raises(ValueError):
            ar.check_html(bad)


def test_filing_codes_keep_their_written_order_inside_arabic():
    text = ar.ltr_tokens("إفصاح عن حدث جوهري (8-K) ونموذج 10-Q وطلب S-1")
    for code in ("8-K", "10-Q", "S-1"):
        assert f"{ar.LRM}{code}{ar.LRM}" in text
    assert ar.ltr_tokens("سهم NVDA بسعر 201.30") == "سهم NVDA بسعر 201.30"  # plain tickers/numbers untouched


def test_naive_times_are_rejected():
    with pytest.raises(ValueError):
        ar.clock_ar(datetime(2026, 11, 18, 15, 5), ar.NEW_YORK)
    assert ar.day_month_ar(date(2026, 10, 20)) == "20 أكتوبر"
