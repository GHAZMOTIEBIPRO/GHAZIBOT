"""Read-only research probe (2026-10-27): product-level terms and candidate official sources.

Prints, without secrets:
- the full text and links of NasdaqTrader's symbol look-up page, the definitions page
  and ai.txt (product notices are read per product, no data file is requested);
- Federal Register document samples from several agencies (titles, abstracts, types);
- USAspending contract awards, CPSC recalls and NHTSA recall samples;
- relevant lines of OPRA and options-vendor licensing pages.
One request per URL, one second apart, no retries.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; GHAZI-source-probe/1.1; research)"}
TODAY = date.today()


def text_lines(html: str) -> list[str]:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?is)<br\s*/?>|</p>|</li>|</div>|</h\d>|</td>", "\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    lines = [re.sub(r"\s+", " ", x).strip() for x in body.splitlines()]
    return [x for x in lines if x]


def get(url, **kw):
    time.sleep(1)
    try:
        r = requests.get(url, headers=UA, timeout=30, **kw)
        return r.status_code, r
    except requests.RequestException as exc:
        return f"NETWORK_{type(exc).__name__}", None


def section(title):
    print(f"\n######## {title}", flush=True)


def nasdaqtrader():
    for url in ("https://www.nasdaqtrader.com/trader.aspx?id=symbollookup",
                "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
                "https://www.nasdaqtrader.com/ai.txt"):
        status, r = get(url)
        section(f"PAGE {url} status={status}")
        if r is None or r.status_code != 200:
            continue
        lines = text_lines(r.text) if "<" in r.text[:500] else r.text.splitlines()
        # The site menu fills the first few hundred lines; the product notices sit lower down.
        notice = re.compile(r"(created, collected|without restriction|licens|retain|terms of serv|copyright|"
                            r"events data|fund network|symbol director|ftp|nasdaqlisted|otherlisted|daily list|"
                            r"security status|ex-date|when (issued|distributed)|ai |crawl|train|bot)", re.I)
        print("  lines:", len(lines))
        for i, line in enumerate(lines):
            if notice.search(line) and len(line) > 25:
                print(f"  [{i}] |", line[:1200])
        if url.endswith("ai.txt"):
            for line in lines[:80]:
                print("  ai |", line[:300])
        links = sorted(set(re.findall(r'href="([^"]+)"', r.text, re.I)))
        print("  DATA LINKS:", json.dumps([x for x in links if re.search(r"(symdir|symboldirectory|dynamic|\.txt|"
                                                                          r"dailylist|ftp|rss|legal|terms)", x, re.I)]))


def federal_register():
    section("FEDERAL REGISTER")
    start = (TODAY - timedelta(days=45)).isoformat()
    for agency in ("food-and-drug-administration", "national-highway-traffic-safety-administration",
                   "federal-trade-commission", "federal-energy-regulatory-commission",
                   "nuclear-regulatory-commission", "federal-aviation-administration"):
        params = {"per_page": 60 if agency.startswith("food") else 15, "order": "newest",
                  "conditions[agencies][]": agency, "conditions[publication_date][gte]": start,
                  "fields[]": ["title", "type", "abstract", "document_number", "publication_date", "html_url",
                               "action", "dates"]}
        status, r = get("https://www.federalregister.gov/api/v1/documents.json", params=params)
        if r is None or r.status_code != 200:
            print(agency, status)
            continue
        d = r.json()
        print(f"== {agency}: count={d.get('count')} shown={len(d.get('results', []))}")
        for doc in d.get("results", []):
            print(json.dumps({k: (str(doc.get(k) or "")[:260]) for k in ("publication_date", "type", "title", "abstract",
                                                                        "document_number", "html_url")},
                             ensure_ascii=False))
    for url in ("https://www.federalregister.gov/reader-aids/using-federalregister-gov/understanding-the-federal-register",
                "https://www.federalregister.gov/developers/documentation/api/v1",
                "https://www.federalregister.gov/policy/privacy"):
        status, r = get(url)
        print(f"-- terms page {url} status={status}")
        if r is not None and r.status_code == 200:
            for line in text_lines(r.text):
                if re.search(r"(public domain|copyright|legal status|official|api key|rate|terms|no restrictions)", line, re.I):
                    print("  |", line[:300])


def usaspending():
    section("USASPENDING CONTRACT AWARDS")
    body = {"filters": {"time_period": [{"start_date": (TODAY - timedelta(days=14)).isoformat(),
                                         "end_date": TODAY.isoformat()}],
                        "award_type_codes": ["A", "B", "C", "D"],
                        "award_amounts": [{"lower_bound": 100000000}]},
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Start Date", "Awarding Agency",
                       "Description", "Last Modified Date", "generated_internal_id", "recipient_id"],
            "limit": 25, "page": 1, "sort": "Award Amount", "order": "desc"}
    time.sleep(1)
    try:
        r = requests.post("https://api.usaspending.gov/api/v2/search/spending_by_award/", json=body, headers=UA, timeout=40)
        print("status", r.status_code)
        if r.status_code == 200:
            d = r.json()
            print("page_metadata", json.dumps(d.get("page_metadata")))
            for row in d.get("results", []):
                print(json.dumps({k: str(row.get(k))[:140] for k in body["fields"]}, ensure_ascii=False))
        else:
            print(r.text[:400])
    except requests.RequestException as exc:
        print("NETWORK", type(exc).__name__)
    status, r = get("https://api.usaspending.gov/docs/data-dictionary")
    print("-- data dictionary page", status)
    status, r = get("https://www.usaspending.gov/about")
    print("-- about", status)
    if r is not None and r.status_code == 200:
        for line in text_lines(r.text):
            if re.search(r"(public|copyright|terms|license|open data|DATA Act)", line, re.I):
                print("  |", line[:300])


def recalls():
    section("CPSC RECALLS")
    status, r = get("https://www.saferproducts.gov/RestWebServices/Recall",
                    params={"format": "json", "RecallDateStart": (TODAY - timedelta(days=30)).isoformat()})
    print("status", status)
    if r is not None and r.status_code == 200:
        rows = r.json()
        print("count", len(rows))
        for row in rows[:12]:
            print(json.dumps({"date": row.get("RecallDate"), "title": str(row.get("Title"))[:140],
                              "manufacturers": [m.get("Name") for m in row.get("Manufacturers") or []][:3],
                              "retailers": [m.get("Name") for m in row.get("Retailers") or []][:3],
                              "url": row.get("URL")}, ensure_ascii=False))
    section("NHTSA RECALLS")
    for url, params in (("https://api.nhtsa.gov/recalls/recallsByVehicle", {"make": "ford", "model": "f-150", "modelYear": "2024"}),
                        ("https://api.nhtsa.gov/products/vehicle/makes", {"issueType": "r"})):
        status, r = get(url, params=params)
        print(url, status)
        if r is not None and r.status_code == 200:
            d = r.json()
            res = d.get("results") or d.get("Results") or []
            print("  count", d.get("Count") or d.get("count") or len(res))
            for row in res[:5]:
                print("  ", json.dumps({k: str(v)[:120] for k, v in list(row.items())[:8]}, ensure_ascii=False))


def options_terms():
    section("OPTIONS DATA LICENSING PAGES")
    for url in ("https://www.opraplan.com/faqs", "https://www.opraplan.com/document-library",
                "https://databento.com/docs/portal/live-data",
                "https://intrinio.com/blog/market-data-licensing-guide-for-fintechs",
                "https://www.marketdata.app/?p=10374"):
        status, r = get(url)
        print(f"-- {url} status={status}")
        if r is not None and r.status_code == 200:
            for line in text_lines(r.text):
                if re.search(r"(redistribut|delayed|non-?professional|display|historical|vendor|fee|internal|"
                             r"external|derived|non-display|license)", line, re.I):
                    print("  |", line[:300])


if __name__ == "__main__":
    for fn in (nasdaqtrader, federal_register, usaspending, recalls, options_terms):
        try:
            fn()
        except Exception as exc:  # a probe reports, it does not stop
            print("PROBE_ERROR", fn.__name__, type(exc).__name__, str(exc)[:200])
