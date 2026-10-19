"""Google RSS matched-name research watch never equals an issuer filing."""
from datetime import datetime, timedelta, timezone
import json

from scripts.build_stock_watch_charts import load_dynamic_symbols
from scripts.stock_watch_news_attention import load_news_attention, news_candidates

NOW = datetime(2026, 10, 19, 0, 35, tzinfo=timezone.utc)


def story(symbol, **kwargs):
    return {
        "symbol": symbol,
        "authority": "NEWS_SEARCH_ATTENTION_ONLY",
        "source_family": "unofficial_google_news_search_rss",
        "issuer_name_in_headline": True,
        "issuer_release_authenticated": False,
        "positive_catalyst_verified": False,
        "market_direction": "UNKNOWN",
        "published_at": (NOW - timedelta(hours=2)).isoformat(),
        "first_collected_at": (NOW - timedelta(hours=1)).isoformat(),
        **kwargs,
    }


def make_feed(tmp_path, rows, *, age_minutes=10):
    p = tmp_path / "news.json"
    p.write_text(json.dumps({
        "schema": "free_public_intelligence_v1",
        "generated_at": (NOW - timedelta(minutes=age_minutes)).isoformat(),
        "google_news_attention": rows,
    }), encoding="utf-8")
    return p


def make_brief(tmp_path):
    p = tmp_path / "brief.json"
    p.write_text(json.dumps({
        "schema": "ghazi.public_decision.v1",
        "source_generated_at": NOW.isoformat(),
        "stocks": [
            {"symbol": "NEWA", "score": 90},
            {"symbol": "NEWB", "score": 89},
            {"symbol": "NEWC", "score": 70},
            {"symbol": "NEWD", "score": 65},
        ]
    }), encoding="utf-8")
    return p


def test_fresh_issuer_named_attention_adds_bounded_discovery_slots(tmp_path):
    feed=make_feed(tmp_path,[story("NXST"),story("XYZ")])
    result=load_news_attention(feed,now=NOW)
    assert set(result)=={"NXST","XYZ"}
    assert not result["NXST"]["official_catalyst_verified"]
    assert not result["NXST"]["live_decision_authority"]
    ranked=load_dynamic_symbols(make_brief(tmp_path),now=NOW,news_path=feed)
    assert len(ranked)==4
    assert ranked[:2]==("NEWA","NEWB")
    assert set(ranked[2:])=={"NXST","XYZ"}
    assert news_candidates(result,fixed=(),radar_choices=("A","B"),maximum=3)==(
        "A","B","NXST"
    )


def test_no_arbitrary_ticker_or_unverified_issuer_name_hijacks_discovery(tmp_path):
    feed=make_feed(tmp_path,[
        story("MALX",issuer_name_in_headline=False),
        story("SPX"), story("RGC",issuer_release_authenticated=True),
        story("NXST",market_direction="UP"),
        story("../"),story("GOOD",published_at=(NOW+timedelta(hours=3)).isoformat()),
        story("XYZ",positive_catalyst_verified=True),
    ])
    assert load_news_attention(feed,now=NOW)=={}
    ranked=load_dynamic_symbols(make_brief(tmp_path),now=NOW,news_path=feed)
    assert ranked[:2]==("NEWA","NEWB")
    assert set(ranked[2:])=={"NEWC","NEWD"}


def test_stale_or_future_news_reports_fail_closed(tmp_path):
    for age in (3000,-10):
        feed=make_feed(tmp_path,[story("NXST")],age_minutes=age)
        assert load_news_attention(feed,now=NOW)=={}
    feed=make_feed(tmp_path,[story("NXST",
        published_at=(NOW-timedelta(days=5)).isoformat())])
    assert load_news_attention(feed,now=NOW)=={}


def test_wrong_schema_and_malformed_feeds_do_not_bypass_symbol_validation(tmp_path):
    p=make_feed(tmp_path,[story("NXST")])
    x=json.loads(p.read_text())
    x["schema"]="unknown"
    p.write_text(json.dumps(x))
    assert load_news_attention(p,now=NOW)=={}
    p.write_text("<html>403 blocked</html>")
    assert load_news_attention(p,now=NOW)=={}
