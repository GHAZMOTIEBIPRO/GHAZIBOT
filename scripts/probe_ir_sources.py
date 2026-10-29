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
    # second round: more non-medical leaders (chips, software, consumer, banks, energy, industry, defence)
    "AMD": "https://ir.amd.com/", "INTC": "https://www.intc.com/", "ORCL": "https://investor.oracle.com/",
    "CRM": "https://investor.salesforce.com/", "NFLX": "https://ir.netflix.net/", "MU": "https://investors.micron.com/",
    "QCOM": "https://investor.qualcomm.com/", "TXN": "https://investor.ti.com/", "IBM": "https://www.ibm.com/investor",
    "PLTR": "https://investors.palantir.com/", "UBER": "https://investor.uber.com/", "COIN": "https://investor.coinbase.com/",
    "KO": "https://investors.coca-colacompany.com/", "PEP": "https://www.pepsico.com/investors",
    "WMT": "https://stock.walmart.com/", "COST": "https://investor.costco.com/", "HD": "https://ir.homedepot.com/",
    "V": "https://investor.visa.com/", "MA": "https://investor.mastercard.com/", "BAC": "https://investor.bankofamerica.com/",
    "GS": "https://www.goldmansachs.com/investor-relations/", "CVX": "https://www.chevron.com/investors",
    "CAT": "https://investors.caterpillar.com/", "GE": "https://www.geaerospace.com/investor-relations",
    "LMT": "https://investors.lockheedmartin.com/", "RTX": "https://investors.rtx.com/",
    "NOC": "https://investor.northropgrumman.com/", "GD": "https://investorrelations.gd.com/",
    "F": "https://shareholder.ford.com/", "GM": "https://investor.gm.com/",
}
FEED_TYPES = ("application/rss+xml", "application/atom+xml")


class FeedLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[tuple[str, str]] = []
        self.news_pages: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "link" and "alternate" in a.get("rel", "").lower() and a.get("type", "").lower() in FEED_TYPES:
            self.feeds.append((a.get("href", ""), a.get("title", "")))
        # Links the page itself shows (IR platforms often put "RSS" in the body or footer); never guessed paths.
        elif tag == "a" and re.search(r"(^|[/._-])rss([/._?-]|$)", a.get("href", ""), re.IGNORECASE):
            self.feeds.append((a.get("href", ""), a.get("title", "") or "page link"))
        # The page's own "press releases / news" links: the feed list often sits there.
        elif tag == "a" and re.search(r"press-releases?|news-releases?|/news(/|$|\?)", a.get("href", ""), re.IGNORECASE):
            self.news_pages.append(a.get("href", ""))


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
    if ok is not True:      # unknown (robots.txt unreadable) fails closed, like disallowed
        return {**row, "status": "ROBOTS_DISALLOWED" if ok is False else "ROBOTS_UNKNOWN"}
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
    seen: set[str] = set()
    queue = [(urljoin(r.url, href), title, 0) for href, title in parser.feeds]
    if not queue:
        # No feed link on the IR home page: read up to two of its own news pages (same site) once.
        host = urlparse(r.url).netloc
        news = [u for u in dict.fromkeys(urljoin(r.url, h) for h in parser.news_pages) if urlparse(u).netloc == host][:2]
        row["news_pages_read"] = []
        for page in news:
            ok, _ = allowed(page)
            if ok is not True:
                continue
            time.sleep(1)
            try:
                n = requests.get(page, timeout=25, headers={"User-Agent": UA, "Accept": "text/html"})
            except requests.RequestException:
                continue
            row["news_pages_read"].append([page, n.status_code])
            if n.status_code == 200:
                sub = FeedLinks()
                sub.feed(n.text)
                queue += [(urljoin(n.url, h), t, 0) for h, t in sub.feeds]
    while queue and len(seen) < 10:
        feed_url, title, depth = queue.pop(0)
        if feed_url in seen or not feed_url.startswith("https://"):
            continue
        seen.add(feed_url)
        entry: dict = {"url": feed_url, "title": title[:80]}
        ok, why = allowed(feed_url)
        if ok is not True:
            feeds.append({**entry, "status": "ROBOTS_DISALLOWED" if ok is False else "ROBOTS_UNKNOWN"})
            continue
        time.sleep(1)
        try:
            f = requests.get(feed_url, timeout=25, headers={"User-Agent": UA})
        except requests.RequestException as exc:
            feeds.append({**entry, "status": "FEED_ERROR", "error": type(exc).__name__})
            continue
        kind = f.headers.get("content-type", "").lower()
        if f.status_code == 200 and "html" in kind and depth == 0:
            # An "RSS" page that lists the company's feeds: follow only what it lists, one level.
            sub = FeedLinks()
            sub.feed(f.text)
            listed = [(urljoin(f.url, h), t, 1) for h, t in sub.feeds]
            # Company news first: press releases and news feeds before events, filings and presentations.
            listed.sort(key=lambda x: 0 if re.search(r"press|news", x[0], re.IGNORECASE) else 1)
            queue += listed
            feeds.append({**entry, "http": f.status_code, "status": "FEED_INDEX_PAGE", "listed": len(sub.feeds)})
            continue
        try:
            got = items(f.text) if f.status_code == 200 else []
            feeds.append({**entry, "http": f.status_code, "items": len(got), "latest": got[0] if got else None})
        except ElementTree.ParseError:
            feeds.append({**entry, "http": f.status_code, "status": "NOT_XML", "content_type": kind[:40]})
    row["feeds"] = feeds
    row["status"] = "FEED_FOUND" if any(x.get("items") for x in feeds) else ("FEED_LINKS_NO_ITEMS" if feeds else "NO_FEED_LINK")
    return row


def main() -> int:
    for symbol, url in IR.items():
        print("IR", json.dumps(probe(symbol, url), ensure_ascii=False), flush=True)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
