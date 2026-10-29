"""Company news from official investor-relations feeds (non-medical leaders and watched names).

Sources are the reviewed rows of data/ir_feeds.json: each is a feed the company's own IR page
links to, found by scripts/probe_ir_sources.py on a runner (run id recorded per row). Every run
reads the host's robots.txt first and skips the feed unless it is readable and allows us; one
request per feed, no retries. Each source carries its own status, so one failing page says
nothing about another, and a failed source keeps its last good items with the time they were
fetched.

What is published per item:
- facts: the company's own headline, its publication time, the link to the release;
- interpretation, kept apart: a category read from the headline's words (our label, not the
  company's) and an impact that stays NEEDS_IMPACT_ASSESSMENT;
- a short summary of our own (company and category), never the release text.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

# Company feeds are untrusted XML: defusedxml (PSF licence, used as a library) refuses entity
# expansion and DTDs, which the stdlib parser would process.
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeElementTree

SCHEMA = "ghazi.ir_news.v1"
ROOT = Path(__file__).resolve().parents[1]
UA = "GHAZI-RADAR-ir-news/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"
WINDOW_DAYS = 30
MAX_ITEMS_PER_SOURCE = 12
# Order matters: a release that announces when results come out is a schedule, not results.
CATEGORIES = [
    ("SCHEDULE", "موعد معلن (نتائج أو مؤتمر أو عرض)",
     r"\bto (release|report|host|present|participate|announce|webcast)\b|conference call|webcast|\bto speak\b"),
    ("EARNINGS", "نتائج مالية", r"\b(quarter|annual|fiscal|full[- ]year)\b.{0,40}\bresults\b|\bfinancial results\b|\bearnings\b|\bresults for\b"),
    ("GUIDANCE", "توقعات الشركة", r"\b(guidance|outlook|forecast)\b"),
    ("FINANCING_DILUTION", "تمويل قد يخفف الملكية",
     r"\b(public offering|registered direct|at-the-market|private placement of (common|shares)|warrants)\b"),
    ("FINANCING", "تمويل أو ديون أو توزيعات",
     r"\b(senior notes|notes due|debt offering|credit facility|convertible|repurchase|buyback|dividend)\b"),
    ("M_AND_A", "استحواذ أو اندماج أو بيع أصول",
     r"\b(acquire|acquires|acquisition|merger|merge|divest|divestiture|to sell|sale of|spin-?off)\b"),
    ("CONTRACT", "عقد أو اتفاقية أو شراكة",
     r"\b(contract|awarded|award|agreement|partnership|collaborat|selected by|order from)\b"),
    ("MANAGEMENT", "تغيير في الإدارة أو المجلس",
     r"\b(appoints|appointed|names .{0,40}(ceo|cfo|chief|president)|resign|retire|board of directors)\b"),
    ("BUSINESS_CHANGE", "تغيير في النشاط", r"\b(restructur|layoff|reorganiz|discontinu|exit(s|ing)? the)\b"),
]


# Filings listed on the company's own IR site: only forms that carry company news; ownership forms are skipped.
FILING_FORMS = [
    (r"^8-K", "FILING_8K", "إفصاح عن حدث جوهري (8-K)"),
    (r"^10-[QK]", "FILING_PERIODIC", "تقرير دوري (10-Q أو 10-K)"),
    (r"^(S-1|S-3|424B\d?|F-3)", "FILING_REGISTRATION", "تسجيل أو نشرة أوراق مالية (قد يعني تمويلًا)"),
    (r"^DEF 14A", "FILING_PROXY", "دعوة جمعية عمومية (DEF 14A)"),
]


def filing_category(title: str) -> tuple[str, str] | None:
    """'Company - FORM - description' as the IR site lists SEC filings; None for forms we do not show."""
    parts = [p.strip() for p in title.split(" - ")]
    form = parts[1] if len(parts) >= 3 else ""
    for pattern, key, label in FILING_FORMS:
        if re.match(pattern, form):
            return key, label
    return None


def category(title: str, kind: str = "press_release") -> tuple[str, str] | None:
    if kind == "sec_filing":
        return filing_category(title)
    if kind == "event":
        return "SCHEDULE", "موعد معلن (نتائج أو مؤتمر أو عرض)"
    for key, label, pattern in CATEGORIES:
        if re.search(pattern, title, re.IGNORECASE):
            return key, label
    return "OTHER", "خبر من الشركة"


def robots_ok(url: str, session: Any) -> tuple[bool, str]:
    """Readable robots.txt that allows us, or no robots.txt at all (HTTP 404/410). Anything else fails closed."""
    parts = urlparse(url)
    try:
        r = session.get(f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=20, headers={"User-Agent": UA})
    except requests.RequestException as exc:
        return False, f"ROBOTS_UNREADABLE ({type(exc).__name__})"
    if r.status_code in (404, 410):
        return True, "NO_ROBOTS_TXT"
    if r.status_code != 200:
        return False, f"ROBOTS_HTTP_{r.status_code}"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return (True, "ROBOTS_ALLOWED") if rp.can_fetch(UA, url) else (False, "ROBOTS_DISALLOWED")


def parse_time(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None              # a time without a zone is not an absolute time
    return dt.astimezone(timezone.utc).isoformat()


def parse_feed(xml: str) -> list[dict[str, str | None]]:
    root = SafeElementTree.fromstring(xml)

    def child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
        return next((c for c in node if c.tag.split("}")[-1] == name), None)

    out = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = child(node, "title")
        link = child(node, "link")
        href = (link.get("href") or link.text or "").strip() if link is not None else ""
        when = next((child(node, n) for n in ("pubDate", "published", "updated") if child(node, n) is not None), None)
        out.append({"title": re.sub(r"\s+", " ", (title.text or "") if title is not None else "").strip(),
                    "url": href, "published_at": parse_time(when.text or "") if when is not None else None})
    return out


def same_site(url: str, feed: dict[str, Any]) -> bool:
    """A release link must stay on the company's own site (the feed's or the IR page's registrable host)."""
    host = urlparse(url).netloc.lower()
    allowed = {urlparse(feed["feed_url"]).netloc.lower(), urlparse(feed["page"]).netloc.lower()}
    base = lambda h: ".".join(h.split(".")[-2:])
    return url.startswith("https://") and (host in allowed or base(host) in {base(h) for h in allowed})


def build(feeds: list[dict[str, Any]], fetched: dict[str, tuple[str, Any]], now: datetime,
          previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """fetched: feed_url -> (status, xml text or None). Pure: no network."""
    cutoff = now - timedelta(days=WINDOW_DAYS)
    prev_sources = {s.get("feed_url"): s for s in (previous or {}).get("sources", []) if isinstance(s, dict)}
    prev_items = [i for i in (previous or {}).get("items", []) if isinstance(i, dict)]
    seen_before = {i.get("url"): i for i in prev_items}
    sources, items = [], []
    for feed in feeds:
        status, text = fetched.get(feed["feed_url"], ("NOT_FETCHED", None))
        src = {k: feed[k] for k in ("symbol", "company", "page", "feed_url", "kind", "probe_run")}
        got: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] | None = None
        if status == "OK" and text is not None:
            try:
                raw = parse_feed(text)
            except ElementTree.ParseError:
                status = "NOT_XML"
            except DefusedXmlException:
                status = "XML_REFUSED_UNSAFE"
        # A feed that did not parse is a failure like any other: last good items kept, no new success time.
        if raw is not None:
            for r in raw:
                if not r["title"] or not same_site(r["url"], feed) or not r["published_at"]:
                    continue
                if datetime.fromisoformat(r["published_at"]) < cutoff:
                    continue
                cat = category(r["title"], feed["kind"])
                if cat is None:
                    continue
                key, label = cat
                old = seen_before.get(r["url"]) or {}
                # An event listing names its own date ("11/17/2026 : ..."): the event time, apart from publication.
                m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*:", r["title"]) if feed["kind"] == "event" else None
                event_at = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None
                got.append({
                    "event_at": event_at,
                    "symbol": feed["symbol"], "company": feed["company"], "source_kind": feed["kind"],
                    "title": r["title"][:220], "url": r["url"], "source_published_at": r["published_at"],
                    # our first fetch of this item: carried once recorded; this run's time only for new items
                    "first_observed_at": old.get("first_observed_at") or now.isoformat(),
                    # an item already in the feed when we first read that source was not detected by us
                    "first_observed_basis": old.get("first_observed_basis") or
                    ("IR_FEED_FETCH" if feed["feed_url"] in prev_sources else "FIRST_FETCH_OF_SOURCE"),
                    "category": key, "category_ar": label, "category_basis": "HEADLINE_KEYWORDS",
                    "potential_impact": "NEEDS_IMPACT_ASSESSMENT",
                    "summary_ar": f"{feed['company_ar']}: {label}",
                })
            got = sorted(got, key=lambda x: x["source_published_at"], reverse=True)[:MAX_ITEMS_PER_SOURCE]
            src.update(status="OK", items=len(got), last_success_at=now.isoformat())
        else:
            # This source only: keep its last good items, marked with when they were fetched.
            old = prev_sources.get(feed["feed_url"]) or {}
            got = [i for i in prev_items if i.get("source_feed") == feed["feed_url"]
                   and datetime.fromisoformat(i["source_published_at"]) >= cutoff]
            src.update(status=status, items=len(got), last_success_at=old.get("last_success_at"),
                       kept_previous=bool(got))
        for g in got:
            g["source_feed"] = feed["feed_url"]
        sources.append(src)
        items += got
    items.sort(key=lambda x: x["source_published_at"], reverse=True)
    return {
        "schema": SCHEMA, "generated_at": now.isoformat(), "window_days": WINDOW_DAYS,
        "policy": ("Official IR feeds linked from each company's own IR page; robots.txt read every run and "
                   "failing closed; headline, time and link are the company's; category is ours, from the "
                   "headline's words; impact is not assessed; no release text is copied."),
        "sources": sources, "items": items,
        "counts": {"sources": len(sources), "sources_ok": sum(s["status"] == "OK" for s in sources),
                   "items": len(items)},
        "research_only": True, "decision_authority": False, "execution_authority": False,
    }


def fetch_all(feeds: list[dict[str, Any]], session: Any) -> dict[str, tuple[str, Any]]:
    out: dict[str, tuple[str, Any]] = {}
    for feed in feeds:
        ok, why = robots_ok(feed["feed_url"], session)
        if not ok:
            out[feed["feed_url"]] = (why, None)
            continue
        time.sleep(1)
        try:
            r = session.get(feed["feed_url"], timeout=25, headers={"User-Agent": UA})
        except requests.RequestException as exc:
            out[feed["feed_url"]] = (f"FETCH_ERROR ({type(exc).__name__})", None)
            continue
        out[feed["feed_url"]] = ("OK", r.text) if r.status_code == 200 else (f"HTTP_{r.status_code}", None)
    return out


def load_feeds(path: Path | None = None) -> list[dict[str, Any]]:
    table = json.loads((path or ROOT / "data" / "ir_feeds.json").read_text(encoding="utf-8"))
    return [f for f in table.get("feeds", []) if isinstance(f.get("probe_run"), int)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = None
    if args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    feeds = load_feeds()
    now = datetime.now(timezone.utc)
    report = build(feeds, fetch_all(feeds, requests), now, previous if (previous or {}).get("schema") == SCHEMA else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "sources": [(s["symbol"], s["status"], s["items"]) for s in report["sources"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
