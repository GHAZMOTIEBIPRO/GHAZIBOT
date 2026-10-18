"""Offline contracts: public-domain GitHub listings + bounded dynamic issuer RSS."""
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import requests

from options_radar.free_public_intelligence import (
    GOOGLE_NEWS_MAX_ISSUERS, google_issuer_attention, retain_verified_news_context,
)
from options_radar.github_listing_discovery import (
    LISTINGS, clean_issuer_name, resolve_public_issuers, symbols_from_brief,
)

NOW = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)


def listing_csv(symbol_column, name_column, rows):
    # 120+ rows: a truncated upstream file is not a safe name directory.
    others = [(f"T{i:04d}", f"Placeholder Company {i} Common Stock")
              for i in range(120)]
    lines = [f"{symbol_column},{name_column}"]
    for symbol, name in others + rows:
        lines.append(f'{symbol},"{name}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class ListingSession:
    def __init__(self, *, bad_nyse=False):
        self.calls = []
        self.bad_nyse = bad_nyse

    def get(self, url, *, timeout=12, headers=None, params=None):
        self.calls.append(url)
        if "nasdaq-listed.csv" in url:
            return Response(listing_csv("Symbol", "Security Name", [
                ("DKNG", "DraftKings Inc. Class A Common Stock"),
                ("REGN", "Regeneron Pharmaceuticals, Inc. Common Stock"),
                ("FUND", "Broad Dividend ETF"),
                ("WARR", "Company One Warrants"),
            ]))
        if "nyse-listed.csv" in url:
            return Response(b"bad data" if self.bad_nyse else listing_csv(
                "ACT Symbol", "Company Name", [
                    ("OXY", "Occidental Petroleum Corporation Common Stock"),
                    ("CVX", "Chevron Corporation Common Stock"),
                    ("ENR", "Some Company Rights"),
                ],
            ))
        raise AssertionError("Unexpected external host")


def test_two_real_repository_endpoints_parse_names_not_market_prices():
    session = ListingSession()
    report = resolve_public_issuers(
        ["DKNG", "REGN", "CVX", "OXY", "FUND", "WARR"],
        now=NOW, session=session,
    )
    assert report["status"] == "AVAILABLE_CONTEXT"
    assert report["issuers"] == {
        "DKNG": "DraftKings", "REGN": "Regeneron Pharmaceuticals",
        "CVX": "Chevron", "OXY": "Occidental Petroleum",
    }
    assert len(session.calls) == len(LISTINGS) == 2
    assert report["source_license"] == "ODC-PDDL-1.0"
    assert report["not_sec_authenticated"] is True
    assert report["not_live_listing_or_price"] is True


def test_directory_cache_limits_provider_calls_and_never_fakes_issuer():
    session = ListingSession()
    first = resolve_public_issuers(["DKNG", "OXY"], now=NOW, session=session)
    previous = {"schema": "free_public_intelligence_v1", "issuer_directory": first}
    fresh = ListingSession()
    cached = resolve_public_issuers(
        ["DKNG", "OXY", "NEWX"], previous=previous,
        now=NOW+timedelta(hours=6), session=fresh,
    )
    assert cached["status"] == "CACHED_GITHUB_LISTINGS"
    assert cached["issuers"] == first["issuers"]
    assert fresh.calls == []
    assert "NEWX" not in cached["issuers"]
    updated = ListingSession(bad_nyse=True)
    restored = resolve_public_issuers(
        ["DKNG", "OXY"], previous=previous,
        now=NOW+timedelta(hours=26), session=updated,
    )
    assert restored["status"] == "PARTIAL_CONTEXT"
    assert "DKNG" in restored["issuers"] and "OXY" not in restored["issuers"]
    assert restored["errors"]["nyse"] == "ValueError"


def test_listing_cleaning_rejects_derivatives_and_ambiguous_names():
    assert clean_issuer_name("Chevron Corporation Common Stock") == "Chevron"
    for name in ("XYZ ETF", "A1 Warrant", "Two Rights", "BAD Units",
                 "<script>alert()</script>", "A", "Holdings"):
        assert clean_issuer_name(name) is None


def test_brief_gate_requires_valid_timestamp_and_schema(tmp_path):
    dest = tmp_path / "brief.json"
    dest.write_text(json.dumps({
        "schema": "ghazi.public_decision.v1",
        "source_generated_at": NOW.isoformat(),
        "stocks": [{"symbol": "DKNG"}, {"symbol": "OXY"},
                   {"symbol": "bad/path"}, {"symbol": "DKNG"}],
    }), encoding="utf-8")
    assert symbols_from_brief(dest, now=NOW) == ("DKNG", "OXY")
    assert symbols_from_brief(dest, now=NOW+timedelta(days=4)) == ()
    assert symbols_from_brief(dest, now=NOW-timedelta(hours=1)) == ()
    assert symbols_from_brief(Path("/tmp/unavailable-ghazi-issuer.json"), now=NOW) == ()


class NewsSession:
    def __init__(self):
        self.calls = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(params["q"])
        date = format_datetime(NOW-timedelta(minutes=30))
        items = (
            '<item><title>DraftKings announces new agreement</title>'
            '<link>https://news.google.com/rss/articles/dkng</link>'
            f'<pubDate>{date}</pubDate></item>'
            '<item><title>Chevron reports quarterly earnings</title>'
            '<link>https://news.google.com/rss/articles/cvx</link>'
            f'<pubDate>{date}</pubDate></item>'
            '<item><title>DKNG stock reports profits</title>'
            '<link>https://news.google.com/rss/articles/bare-ticker</link>'
            f'<pubDate>{date}</pubDate></item>'
        )
        return Response(('<rss version="2.0"><channel>'+items+'</channel></rss>').encode())


def test_new_stocks_receive_company_name_news_without_more_than_six_queries():
    names = {"DKNG": "DraftKings", "CVX": "Chevron",
             "OXY": "Occidental Petroleum", "REGN": "Regeneron Pharmaceuticals"}
    symbols = list(names)+["RGC","RKLB","AAPL","NVDA","AMD","SOFI","TSLA","AVGO"]
    session = NewsSession()
    result, errors = google_issuer_attention(
        symbols, session=session, now=NOW, dynamic_names=names,
    )
    assert errors == {}
    assert len(session.calls) <= GOOGLE_NEWS_MAX_ISSUERS
    assert any('"DraftKings"' in query or '"Chevron"' in query
               for query in session.calls)
    assert all(item["issuer_name_in_headline"] is True for item in result)
    assert all(item["positive_catalyst_verified"] is False for item in result)
    assert all(item["market_direction"] == "UNKNOWN" for item in result)
    assert all(item["symbol"] != "DKNG" or "DraftKings" in item["headline"]
               for item in result)
    assert all(item["url"] != "https://news.google.com/rss/articles/bare-ticker"
               for item in result)


def test_dynamic_story_retention_requires_same_valid_issuer_name():
    news = {
        "schema": "free_public_intelligence_v1",
        "generated_at": NOW.isoformat(),
        "google_news_attention": [],
    }
    older = {
        "generated_at": (NOW-timedelta(hours=3)).isoformat(),
        "google_news_attention": [{
            "symbol": "DKNG",
            "headline": "DraftKings announces new agreement",
            "url": "https://news.google.com/rss/articles/dkng",
            "published_at": (NOW-timedelta(days=1)).isoformat(),
            "authority": "NEWS_SEARCH_ATTENTION_ONLY",
            "positive_catalyst_verified": False,
            "issuer_release_authenticated": False,
            "market_direction": "UNKNOWN",
        }],
    }
    assert retain_verified_news_context(
        dict(news), older, now=NOW,
    )["google_news_attention"] == []
    kept = retain_verified_news_context(
        dict(news), older, now=NOW, dynamic_names={"DKNG":"DraftKings"},
    )["google_news_attention"]
    assert len(kept) == 1
    assert kept[0]["first_collected_at"] == older["generated_at"]
    assert kept[0]["positive_catalyst_verified"] is False


def test_workflow_consumes_same_existing_state_without_second_schedule():
    workflow = Path(".github/workflows/company-news-watch.yml").read_text()
    code = Path("options_radar/free_public_intelligence.py").read_text()
    assert "--discovery-brief .ghazi-news-state/runtime/public/data/decision_brief.json" in workflow
    assert "--discovery-brief" in code
    assert "source_cooldowns" in code
    assert "issuer_directory" in code
    assert "github_public_listing_mirrors" in code
    assert "workflow_dispatch" in workflow
    assert "cron:" not in workflow
