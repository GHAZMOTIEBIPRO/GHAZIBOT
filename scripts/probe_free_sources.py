"""One small, read-only request per candidate source, by data category.

For each candidate this prints: whether data came back, its shape (fields,
row counts), its freshness (Last-Modified or the provider's own timestamp)
and the relevant terms lines. It never prints a secret: only whether the SEC
User-Agent secret is configured. SEC requests are spaced one second apart (the
fair-access limit is ten per second) and none is retried; a refusal is
recorded, not worked around.

The NasdaqTrader symbol files are checked with HEAD only. The site's own
copyright page (read in full, rights matrix ``nasdaqtrader``) says the content
may not be "stored for subsequent use or otherwise used ... without the prior
written consent of Nasdaq"; the probe therefore reads the product pages to look
for a product-specific grant and does not download the files.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time

import requests

DEFAULT_SEC_AGENT = "GHAZI Radar Research ghazi-bot@users.noreply.github.com"
WEB_UA = {"User-Agent": "Mozilla/5.0 (compatible; GHAZI-source-probe/1.0; research)"}
TERMS = re.compile(r"(licen[cs]|copyright|terms|redistribut|commercial|permission|consent|free of charge|"
                   r"public domain|attribution|automat|personal use|may not|may be used|ftp)", re.IGNORECASE)


def _sec_headers() -> dict[str, str]:
    agent = os.getenv("SEC_USER_AGENT", "").strip() or DEFAULT_SEC_AGENT
    return {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}


def _text(html: str) -> list[str]:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", "\n", body)
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    return [line for line in lines if line]


def _kind(status: int, body: str) -> str:
    if status == 200:
        return "OK"
    if status == 429 or "Request Rate Threshold Exceeded" in body:
        return "RATE_LIMITED"
    if "Undeclared Automated Tool" in body:
        return "IDENTITY_REFUSED"
    if "abuse-detection" in body:
        return "BOT_PROTECTION"
    return f"HTTP_{status}"


def _get(url: str, headers: dict, method: str = "GET", timeout: float = 25, **kw) -> tuple[dict, requests.Response | None]:
    started = time.monotonic()
    try:
        r = requests.request(method, url, headers=headers, timeout=timeout, allow_redirects=True, **kw)
    except requests.RequestException as exc:
        return {"url": url, "kind": f"NETWORK_{type(exc).__name__}"}, None
    head = r.text[:6000] if method == "GET" and r.status_code != 200 else ""
    meta = {"url": url, "status": r.status_code, "kind": _kind(r.status_code, head + r.url),
            "final_host": r.url.split("/")[2], "seconds": round(time.monotonic() - started, 2),
            "last_modified": r.headers.get("Last-Modified"), "content_length": r.headers.get("Content-Length"),
            "content_type": (r.headers.get("Content-Type") or "")[:60]}
    return meta, r


def _terms_lines(r: requests.Response | None, limit: int = 14) -> list[str]:
    if r is None or r.status_code != 200:
        return []
    return [line[:300] for line in _text(r.text) if TERMS.search(line)][:limit]


def nasdaqtrader() -> list[dict]:
    out = []
    for page in ("symbollookup", "symboldirdefs"):
        meta, r = _get(f"https://www.nasdaqtrader.com/trader.aspx?id={page}", WEB_UA)
        meta["terms_lines"] = _terms_lines(r)
        if r is not None and r.status_code == 200 and page == "symboldirdefs":
            meta["field_lines"] = [line[:160] for line in _text(r.text)
                                   if re.match(r"^(Symbol|Security Name|Market Category|Test Issue|Financial Status|"
                                               r"Round Lot Size|ETF|NextShares|Exchange|ACT Symbol|CQS Symbol|"
                                               r"NASDAQ Symbol)", line)][:20]
        out.append(meta)
        time.sleep(1)
    meta, r = _get("https://www.nasdaqtrader.com/robots.txt", WEB_UA)
    meta["body"] = r.text[:600] if r is not None and r.status_code == 200 else None
    out.append(meta)
    for name in ("nasdaqlisted.txt", "otherlisted.txt"):
        time.sleep(1)
        meta, _ = _get(f"https://www.nasdaqtrader.com/dynamic/SymDir/{name}", WEB_UA, method="HEAD")
        meta["note"] = "HEAD only; contents not downloaded (site terms require written consent)"
        out.append(meta)
    return out


def sec() -> list[dict]:
    h = _sec_headers()
    out = []
    meta, r = _get("https://www.sec.gov/files/company_tickers_exchange.json", h)
    if r is not None and r.status_code == 200:
        d = r.json()
        rows = d.get("data") or []
        fields = d.get("fields") or []
        ex = {}
        for row in rows:
            ex[row[fields.index("exchange")] if "exchange" in fields else None] = ex.get(
                row[fields.index("exchange")] if "exchange" in fields else None, 0) + 1
        meta.update(fields=fields, rows=len(rows), by_exchange=dict(sorted(ex.items(), key=lambda kv: -kv[1])))
    out.append(meta)
    for url, method in (
        ("https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip", "HEAD"),
        ("https://www.sec.gov/Archives/edgar/full-index/2026/QTR4/form.idx", "HEAD"),
        ("https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json", "GET"),
        ("https://data.sec.gov/submissions/CIK0000320193.json", "GET"),
        ("https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2025.json", "HEAD"),
        ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=10&output=atom", "GET"),
        ("https://efts.sec.gov/LATEST/search-index?q=%228-K%22&dateRange=custom&forms=8-K", "GET"),
    ):
        time.sleep(1)
        meta, r = _get(url, h, method=method)
        if r is not None and r.status_code == 200 and url.endswith("index.json"):
            items = (r.json().get("directory") or {}).get("item") or []
            names = sorted(i.get("name", "") for i in items if i.get("name", "").startswith("form."))
            meta.update(daily_form_files=len(names), latest_daily=names[-3:])
        if r is not None and r.status_code == 200 and "output=atom" in url:
            meta["entries"] = r.text.count("<entry>")
            m = re.search(r"<updated>([^<]+)</updated>", r.text)
            meta["feed_updated"] = m.group(1) if m else None
        if r is not None and r.status_code == 200 and "CIK0000320193" in url:
            d = r.json()
            meta.update(tickers=d.get("tickers"), exchanges=d.get("exchanges"),
                        recent_filings=len((d.get("filings") or {}).get("recent", {}).get("form", [])))
        out.append(meta)
    return out


def sp500_dataset() -> list[dict]:
    base = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/"
    out = []
    meta, r = _get(base + "data/constituents.csv", WEB_UA)
    if r is not None and r.status_code == 200:
        rows = list(csv.DictReader(io.StringIO(r.text)))
        sectors = {}
        for row in rows:
            sectors[row.get("GICS Sector")] = sectors.get(row.get("GICS Sector"), 0) + 1
        meta.update(rows=len(rows), header=list(rows[0].keys()) if rows else [], sectors=sectors,
                    sample=[row.get("Symbol") for row in rows[:5]])
    out.append(meta)
    meta, r = _get(base + "datapackage.json", WEB_UA)
    if r is not None and r.status_code == 200:
        d = r.json()
        meta.update(licenses=d.get("licenses"), sources=d.get("sources"))
    out.append(meta)
    meta, r = _get(base + "README.md", WEB_UA)
    meta["readme_lines"] = [line[:240] for line in (r.text.splitlines() if r is not None and r.status_code == 200 else [])
                            if re.search(r"(wikipedia|source|licen|update|scrap|constituent)", line, re.I)][:12]
    out.append(meta)
    meta, r = _get("https://api.github.com/repos/datasets/s-and-p-500-companies/commits?path=data/constituents.csv&per_page=3",
                   {"Accept": "application/vnd.github+json", **WEB_UA})
    if r is not None and r.status_code == 200:
        meta["last_data_commits"] = [(c["commit"]["committer"]["date"], c["commit"]["message"][:80]) for c in r.json()]
    out.append(meta)
    return out


def listing_mirrors() -> list[dict]:
    """The GitHub listing mirrors already read by github_listing_discovery.py: origin, licence, age."""
    out = []
    for repo, data_path in (("nasdaq-listings", "data/nasdaq-listed.csv"),
                            ("nyse-other-listings", "data/nyse-listed.csv")):
        base = f"https://raw.githubusercontent.com/datasets/{repo}/main/"
        meta, r = _get(base + "datapackage.json", WEB_UA)
        if r is not None and r.status_code == 200:
            d = r.json()
            meta.update(licenses=d.get("licenses"), sources=d.get("sources"))
        out.append(meta)
        meta, r = _get(base + "README.md", WEB_UA)
        meta["readme_lines"] = [line[:240] for line in (r.text.splitlines() if r is not None and r.status_code == 200 else [])
                                if re.search(r"(nasdaqtrader|ftp|source|licen|update|scrap)", line, re.I)][:10]
        out.append(meta)
        meta, r = _get(f"https://api.github.com/repos/datasets/{repo}/commits?path={data_path}&per_page=2",
                       {"Accept": "application/vnd.github+json", **WEB_UA})
        if r is not None and r.status_code == 200:
            meta["last_data_commits"] = [(c["commit"]["committer"]["date"], c["commit"]["message"][:80]) for c in r.json()]
        out.append(meta)
    return out


def news_and_official() -> list[dict]:
    out = []
    meta, r = _get("https://api.fda.gov/drug/drugsfda.json?limit=1", WEB_UA)
    if r is not None and r.status_code == 200:
        m = r.json().get("meta") or {}
        meta.update(last_updated=m.get("last_updated"), terms=m.get("terms"), license=m.get("license"))
    out.append(meta)
    meta, r = _get("https://clinicaltrials.gov/api/v2/version", WEB_UA)
    if r is not None and r.status_code == 200:
        meta.update(r.json())
    out.append(meta)
    meta, r = _get("https://www.federalregister.gov/api/v1/documents.json?per_page=2&order=newest"
                   "&conditions[agencies][]=food-and-drug-administration", WEB_UA)
    if r is not None and r.status_code == 200:
        meta["latest"] = [(d.get("publication_date"), d.get("type"), (d.get("title") or "")[:90])
                          for d in r.json().get("results", [])]
    out.append(meta)
    meta, r = _get("https://www.federalregister.gov/reader-aids/developer-resources/rest-api", WEB_UA)
    meta["terms_lines"] = _terms_lines(r, 8)
    out.append(meta)
    return out


def economy() -> list[dict]:
    out = []
    meta, _ = _get("https://fred.stlouisfed.org/", WEB_UA, timeout=20)
    out.append(meta)
    meta, r = _get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates"
                   "?sort=-record_date&page[size]=1", WEB_UA)
    if r is not None and r.status_code == 200:
        meta["latest_record_date"] = (r.json().get("data") or [{}])[0].get("record_date")
    out.append(meta)
    return out


def main() -> int:
    report = {"sec_user_agent_secret_configured": bool(os.getenv("SEC_USER_AGENT_SECRET_SET")),
              "probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, fn in (("symbol_directory_nasdaqtrader", nasdaqtrader), ("sec_filings_and_directory", sec),
                     ("large_cap_universe_sp500_dataset", sp500_dataset), ("github_listing_mirrors", listing_mirrors),
                     ("news_official", news_and_official),
                     ("economy", economy)):
        report[name] = fn()
        print(json.dumps({name: report[name]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
