from __future__ import annotations

from options_radar.halt_news_engine import (
    _headline_sentiment,
    _parse_release_feed,
    _symbols_from_release_text,
)


def test_globenewswire_stock_category_maps_exact_ticker() -> None:
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'><channel><item>
      <title>Super Micro Computer Announces New Platform</title>
      <link>https://example.test/smci</link>
      <pubDate>Fri, 04 Sep 2026 15:00:00 GMT</pubDate>
      <category domain='https://www.globenewswire.com/rss/stock'>Nasdaq:SMCI</category>
      <description>Company release.</description>
    </item></channel></rss>"""
    events = _parse_release_feed(
        xml,
        known_symbols={"SMCI", "AAPL"},
        source="GlobeNewswire company release",
        provider="globenewswire_rss",
    )
    assert len(events) == 1
    assert events[0].symbol == "SMCI"
    assert events[0].provider == "globenewswire_rss"
    assert events[0].relevance == 0.90


def test_release_text_avoids_short_word_ticker_false_positives() -> None:
    symbols = _symbols_from_release_text(
        "AI is on the agenda while Apple discusses products.",
        known_symbols={"AI", "ON", "AAPL"},
    )
    assert symbols == []
    assert _symbols_from_release_text("NASDAQ:AI announces results", {"AI", "ON"}) == ["AI"]


def test_business_wire_style_exchange_tag_is_recognized() -> None:
    symbols = _symbols_from_release_text(
        "Palantir Technologies (NYSE: PLTR) announces a new agreement.",
        known_symbols={"PLTR", "P", "AI"},
    )
    assert symbols == ["PLTR"]


def test_headline_sentiment_is_bounded_context_only() -> None:
    assert _headline_sentiment("Company wins contract and raises guidance") > 0
    assert _headline_sentiment("Company announces public offering") < 0
    assert _headline_sentiment("Company schedules annual meeting") == 0
