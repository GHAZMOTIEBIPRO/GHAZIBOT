"""News alert template (BLACK BOX Ω): kind, first seen, age, no invented price; synthetic data only."""
from scripts import send_news_flash_24x7 as flash

BASE = {"symbol": "TEST", "headline": "8-K TEST CORP (synthetic): Item 2.02 Results of Operations", "source": "SEC EDGAR",
        "provider": "sec", "url": "https://www.sec.gov/Archives/edgar/data/0/0.htm", "published": "2026-11-27T13:05:00+00:00",
        "first_seen_at": "2026-11-27T13:06:10+00:00", "bias": "NEUTRAL", "age_minutes": 1.2, "reaction": None,
        "reaction_state": "UNPRICED", "material_reasons": ["نتائج"], "source_class": "OFFICIAL"}


def test_new_update_and_follow_up_are_labelled():
    assert flash.event_kind(BASE) == "NEW"
    assert flash.event_kind({**BASE, "headline": "8-K/A TEST CORP (synthetic)"}) == "UPDATE"
    assert flash.event_kind({**BASE, "updated_at": "2026-11-27T13:20:00+00:00"}) == "FOLLOW_UP"


def test_message_shows_publication_first_seen_age_and_no_invented_price():
    text = flash.format_message(BASE)
    assert text.startswith("⚡ <b>BLACK BOX Ω | جديد | TEST</b>")
    assert "النشر: 2026-11-27 16:05" in text and "أول رصد: 16:06:10" in text and "العمر عند الرصد: 1د" in text
    assert "رد فعل السعر: غير متاح" in text and "الخبر وحده ليس إشارة دخول" in text and len(text) < 4096
    unknown = flash.format_message({**BASE, "first_seen_at": None})
    assert "أول رصد: غير متاح" in unknown


def test_html_in_a_headline_is_escaped():
    text = flash.format_message({**BASE, "headline": "<script>x</script> & co"})
    assert "<script>" not in text and "&lt;script&gt;" in text and "&amp; co" in text


def test_latency_summary_uses_only_known_publication_times():
    recs = [{**BASE, "telegram_accepted_at": "2026-11-27T13:06:12+00:00"},
            {**BASE, "published": "", "first_seen_at": "2026-11-27T13:06:10+00:00"}]
    s = flash.latency_summary(recs)
    assert s["publish_to_detect"] == {"n": 1, "p50_s": 70.0, "p95_s": 70.0}
    assert s["publish_to_telegram"] == {"n": 1, "p50_s": 72.0, "p95_s": 72.0}
