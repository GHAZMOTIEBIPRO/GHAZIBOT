from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import build_ir_news as ir

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 28, 21, tzinfo=timezone.utc)
XOM = {"symbol": "XOM", "company": "Exxon Mobil Corporation", "company_ar": "إكسون موبيل",
       "page": "https://investor.exxonmobil.com/", "kind": "press_release", "probe_run": 1,
       "feed_url": "https://investor.exxonmobil.com/company-information/press-releases/rss"}
NVDA_EVENT = {**XOM, "symbol": "NVDA", "company": "NVIDIA Corporation", "company_ar": "إنفيديا",
              "page": "https://investor.nvidia.com/", "kind": "event", "feed_url": "https://investor.nvidia.com/rss/event.aspx"}
NVDA_SEC = {**NVDA_EVENT, "kind": "sec_filing", "feed_url": "https://investor.nvidia.com/rss/SECFiling.aspx?x=1"}


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{d}</pubDate></item>" for t, u, d in items)
    return f"<rss><channel>{body}</channel></rss>"


XOM_XML = rss(
    ("ExxonMobil to Release Third Quarter 2026 Financial Results", "https://investor.exxonmobil.com/news/1", "Fri, 16 Oct 2026 15:00:00 -0400"),
    ("ExxonMobil Announces Third Quarter 2026 Results", "https://investor.exxonmobil.com/news/2", "Fri, 30 Oct 2026 06:30:00 -0400"),
    ("ExxonMobil completes acquisition of Example Resources", "https://corporate.exxonmobil.com/news/3", "Mon, 05 Oct 2026 08:00:00 -0400"),
    ("Old news", "https://investor.exxonmobil.com/news/4", "Mon, 01 Jun 2026 08:00:00 -0400"),
    ("Look elsewhere", "https://evil.example/news/5", "Mon, 26 Oct 2026 08:00:00 -0400"),
    ("No zone given", "https://investor.exxonmobil.com/news/6", "2026-10-20T10:00:00"))
SEC_XML = rss(
    ("NVIDIA Corporation - 4/A - Amended Statement of Changes in Beneficial Ownership", "https://investor.nvidia.com/f/1", "Tue, 13 Oct 2026 00:00:00 -0400"),
    ("NVIDIA Corporation - 8-K - Current report", "https://investor.nvidia.com/f/2", "Wed, 21 Oct 2026 00:00:00 -0400"),
    ("NVIDIA Corporation - 424B2 - Prospectus", "https://investor.nvidia.com/f/3", "Thu, 22 Oct 2026 00:00:00 -0400"))
EVENT_XML = rss(("11/17/2026 : NVIDIA 3rd Quarter FY27 Financial Results", "https://investor.nvidia.com/e/1", "Wed, 28 Oct 2026 17:00:15 -0400"))


def test_headline_facts_and_our_category_are_kept_apart_and_only_the_companys_site_is_linked():
    r = ir.build([XOM], {XOM["feed_url"]: ("OK", XOM_XML)}, NOW)
    by_url = {i["url"]: i for i in r["items"]}
    # off-site link, items older than the window and times without a zone are dropped
    assert set(by_url) == {"https://investor.exxonmobil.com/news/1", "https://investor.exxonmobil.com/news/2",
                           "https://corporate.exxonmobil.com/news/3"}
    assert by_url["https://investor.exxonmobil.com/news/1"]["category"] == "SCHEDULE"     # a date, not results
    assert by_url["https://investor.exxonmobil.com/news/2"]["category"] == "EARNINGS"
    assert by_url["https://corporate.exxonmobil.com/news/3"]["category"] == "M_AND_A"
    item = by_url["https://investor.exxonmobil.com/news/2"]
    assert item["title"] == "ExxonMobil Announces Third Quarter 2026 Results"           # the company's headline
    assert item["category_basis"] == "HEADLINE_KEYWORDS" and item["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT"
    assert item["summary_ar"] == "إكسون موبيل: نتائج مالية" and item["source_published_at"].startswith("2026-10-30T10:30")


def test_event_dates_and_filing_forms():
    r = ir.build([NVDA_EVENT, NVDA_SEC], {NVDA_EVENT["feed_url"]: ("OK", EVENT_XML), NVDA_SEC["feed_url"]: ("OK", SEC_XML)}, NOW)
    ev = next(i for i in r["items"] if i["source_kind"] == "event")
    assert ev["category"] == "SCHEDULE" and ev["event_at"] == "2026-11-17" and ev["source_published_at"].startswith("2026-10-28")
    forms = sorted(i["category"] for i in r["items"] if i["source_kind"] == "sec_filing")
    assert forms == ["FILING_8K", "FILING_REGISTRATION"]                                   # Form 4/A skipped


def test_each_source_fails_alone_keeps_its_last_good_items_and_first_observed_is_not_invented():
    first = ir.build([XOM, NVDA_EVENT], {XOM["feed_url"]: ("OK", XOM_XML), NVDA_EVENT["feed_url"]: ("OK", EVENT_XML)}, NOW)
    assert {i["first_observed_basis"] for i in first["items"]} == {"FIRST_FETCH_OF_SOURCE"}
    later = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
    more = XOM_XML.replace("</channel>", "<item><title>ExxonMobil awarded contract</title><link>https://investor.exxonmobil.com/news/9"
                           "</link><pubDate>Thu, 29 Oct 2026 08:00:00 -0400</pubDate></item></channel>")
    second = ir.build([XOM, NVDA_EVENT], {XOM["feed_url"]: ("OK", more), NVDA_EVENT["feed_url"]: ("ROBOTS_HTTP_403", None)},
                      later, first)
    src = {s["feed_url"]: s for s in second["sources"]}
    assert src[XOM["feed_url"]]["status"] == "OK"
    nv = src[NVDA_EVENT["feed_url"]]
    assert nv["status"] == "ROBOTS_HTTP_403" and nv["kept_previous"] and nv["last_success_at"] == NOW.isoformat()
    items = {i["url"]: i for i in second["items"]}
    assert items["https://investor.exxonmobil.com/news/9"]["first_observed_basis"] == "IR_FEED_FETCH"
    assert items["https://investor.exxonmobil.com/news/9"]["first_observed_at"] == later.isoformat()
    assert items["https://investor.exxonmobil.com/news/1"]["first_observed_at"] == NOW.isoformat()   # carried unchanged
    assert "https://investor.nvidia.com/e/1" in items                                                  # kept from last good


class FakeSession:
    def __init__(self, robots):
        self.robots, self.calls = robots, []

    def get(self, url, **_):
        self.calls.append(url)
        status, text = self.robots if url.endswith("/robots.txt") else (200, "<rss/>")
        return type("R", (), {"status_code": status, "text": text})()


def test_robots_must_be_readable_and_allow_us_before_any_feed_request(monkeypatch):
    monkeypatch.setattr(ir.time, "sleep", lambda _: None)
    for robots, expected in (((403, ""), "ROBOTS_HTTP_403"), ((200, "User-agent: *\nDisallow: /"), "ROBOTS_DISALLOWED"),
                             ((500, ""), "ROBOTS_HTTP_500")):
        s = FakeSession(robots)
        assert ir.fetch_all([XOM], s)[XOM["feed_url"]][0] == expected
        assert all(u.endswith("/robots.txt") for u in s.calls)                 # the feed itself was never requested
    ok = FakeSession((200, "User-agent: *\nAllow: /"))
    assert ir.fetch_all([XOM], ok)[XOM["feed_url"]][0] == "OK"


def test_ir_items_enter_the_catalyst_list_with_company_source_and_unassessed_impact():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cw_ir_test", ROOT / "scripts" / "build_catalyst_watchlist.py")
    cw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cw)
    news = ir.build([XOM, NVDA_SEC], {XOM["feed_url"]: ("OK", XOM_XML), NVDA_SEC["feed_url"]: ("OK", SEC_XML)}, NOW)
    rows = cw.ir_catalysts(news)
    kinds = {r["kind"] for r in rows}
    assert {"IR_SCHEDULE", "IR_EARNINGS", "IR_M_AND_A", "IR_FILING_8K", "IR_FILING_REGISTRATION"} <= kinds
    assert all(r["source"] == "Company IR" and r["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT" for r in rows)
    report = cw.build(None, None, None, NOW, ir=news)
    assert report["sources"]["company_ir"] is True
    nv = next(e for e in report["watchlist"] if e["symbol"] == "NVDA")
    assert "تسجيل أوراق مالية (تمويل محتمل)" in nv["risk_flags"]           # registration is flagged, not praised
    assert all(c["impact"] in ("RISK", "COMPANY_NEWS_IMPACT_UNASSESSED") for c in nv["catalysts"])
    assert cw.ir_catalysts({"schema": "other"}) == []


def test_shipped_feed_table_rows_carry_their_probe_run():
    table = json.loads((ROOT / "data" / "ir_feeds.json").read_text(encoding="utf-8"))
    assert table["feeds"] and all(isinstance(f["probe_run"], int) and f["feed_url"].startswith("https://") for f in table["feeds"])
    assert len(ir.load_feeds()) == len(table["feeds"])
