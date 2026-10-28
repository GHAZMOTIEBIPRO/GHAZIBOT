"""One-time probe of official investor-relations pages (non-medical leaders and watched names).

For each company: robots.txt is read first and the page is fetched only if allowed for
our user agent; the page is fetched once; only feeds the page itself advertises
(<link rel="alternate" type="application/rss+xml|atom+xml">) are followed, once.
Each source is logged on its own line: a failure of one page says nothing about another,
and nothing here is generalised to a newswire. Titles are printed for review only;
nothing is stored or published.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests

UA = "GHAZI-RADAR-ir-probe/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"
# Official IR home pages, to be confirmed by this probe (a wrong guess shows up as such).
IR = {
    "NVDA": "https://investor.nvidia.com/", "AAPL": "https://investor.apple.com/",
    "MSFT": "https://www.microsoft.com/en-us/investor", "AMZN": "https://ir.aboutamazon.com/",
    "GOOGL": "https://abc.xyz/investor/", "META": "https://investor.atmeta.com/",
    "AVGO": "https://investors.broadcom.com/", "TSLA": "https://ir.tesla.com/",
    "BRK.B": "https://www.berkshirehathaway.com/", "JPM": "https://www.jpmorganchase.com/ir",
    "XOM": "https://investor.exxonmobil.com/", "BA": "https://investors.boeing.com/",
    "RKLB": "https://investors.rocketlabusa.com/", "IONQ": "https://investors.ionq.com/",
    "SOUN": "https://investors.soundhound.com/", "ASTS": "https://investors.ast-science.com/",
}
FEED_TYPES = ("application/rss+xml", "application/atom+xml")


class FeedLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "link" and "alternate" in a.get("rel", "").lower() and a.get("type", "").lower() in FEED_TYPES:
            self.feeds.append((a.get("href", ""), a.get("title", "")))


def allowed(url: str) -> tuple[bool | None, str]:
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/robots.txt"
    try:
        r = requests.get(root, timeout=20, headers={"User-Agent": UA})
    except requests.RequestException as exc:
        return None, f"robots fetch failed: {type(exc).__name__}"
    if r.status_code in (401, 403):
        return False, f"robots.txt HTTP {r.status_code} (treated as disallowed)"
    if r.status_code >= 400:
        return True, f"no robots.txt (HTTP {r.status_code})"
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(UA, url), "robots.txt read"


def items(xml: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml)
    out = []
    def get(node: ElementTree.Element, name: str) -> str:
        return next((c.text or "" for c in node if c.tag.split("}")[-1] == name), "")

    for node in root.iter():
        if node.tag.split("}")[-1] in ("item", "entry"):
            out.append({"title": get(node, "title").strip()[:140],
                        "date": (get(node, "pubDate") or get(node, "published") or get(node, "updated")).strip()[:40]})
    return out


def probe(symbol: str, url: str) -> dict:
    row: dict = {"symbol": symbol, "page": url}
    ok, why = allowed(url)
    row["robots"] = why
    if ok is False:
        return {**row, "status": "ROBOTS_DISALLOWED"}
    time.sleep(1)
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": UA, "Accept": "text/html"})
    except requests.RequestException as exc:
        return {**row, "status": "PAGE_ERROR", "error": type(exc).__name__}
    row.update(http=r.status_code, final_url=r.url, content_type=r.headers.get("content-type", "")[:60])
    if r.status_code != 200:
        return {**row, "status": f"PAGE_HTTP_{r.status_code}"}
    parser = FeedLinks()
    parser.feed(r.text)
    row["terms_link_on_page"] = bool(re.search(r"href=[\"'][^\"']*(terms|legal|disclaimer)", r.text, re.IGNORECASE))
    feeds = []
    for href, title in parser.feeds[:4]:
        feed_url = urljoin(r.url, href)
        entry: dict = {"url": feed_url, "title": title[:80]}
        ok, why = allowed(feed_url)
        if ok is False:
            feeds.append({**entry, "status": "ROBOTS_DISALLOWED"})
            continue
        time.sleep(1)
        try:
            f = requests.get(feed_url, timeout=25, headers={"User-Agent": UA})
            got = items(f.text) if f.status_code == 200 else []
            feeds.append({**entry, "http": f.status_code, "items": len(got), "latest": got[0] if got else None})
        except (requests.RequestException, ElementTree.ParseError) as exc:
            feeds.append({**entry, "status": "FEED_ERROR", "error": type(exc).__name__})
    row["feeds"] = feeds
    row["status"] = "FEED_ADVERTISED" if feeds else "NO_FEED_ADVERTISED"
    return row


def main() -> int:
    for symbol, url in IR.items():
        print("IR", json.dumps(probe(symbol, url), ensure_ascii=False), flush=True)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
