"""Diagnostic: fetch providers' official terms pages and print the clauses
about automated access, redistribution and personal use. Read-only."""
from __future__ import annotations

import html
import re

import requests

PAGES = {
    "yahoo_tos": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    "yahoo_api_terms": "https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html",
    "yahoo_query1_robots": "https://query1.finance.yahoo.com/robots.txt",
    "yahoo_query2_robots": "https://query2.finance.yahoo.com/robots.txt",
    "nasdaq_legal": "https://www.nasdaq.com/legal",
    "nasdaq_api_robots": "https://api.nasdaq.com/robots.txt",
    "nasdaq_www_robots": "https://www.nasdaq.com/robots.txt",
    "nasdaqtrader_symdir": "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
    "cboe_delayed_quotes": "https://www.cboe.com/delayed_quotes/spx/quote_table",
    "cboe_terms": "https://www.cboe.com/about/legal/terms_of_use/",
    "alpaca_data_docs": "https://docs.alpaca.markets/docs/about-market-data-api",
    "alpaca_redistribute": "https://alpaca.markets/support/redistribute-alpaca-api",
    "tiingo_tos": "https://app.tiingo.com/tos/",
    "tiingo_pricing": "https://www.tiingo.com/about/pricing",
    "cftc_cot_api": "https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=1",
    "treasury_yields": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value=2026",
}
KEYWORDS = re.compile(r"(automat|scrap|robot|spider|crawl|redistribut|personal|non-?commercial|"
                      r"commercial|display|derived|extract|download|reproduc|permission|license|"
                      r"internal use|store|cache|disallow|user-agent)", re.IGNORECASE)
UA = {"User-Agent": "Mozilla/5.0 (compatible; GHAZI-terms-review/1.0; research)"}


def text_of(body: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", "\n", body)
    return html.unescape(re.sub(r"[ \t\r\f\v]+", " ", body))


def main() -> int:
    for name, url in PAGES.items():
        print(f"\n===== {name} | {url}")
        try:
            r = requests.get(url, headers=UA, timeout=25)
        except requests.RequestException as exc:
            print(f"FETCH_ERROR {type(exc).__name__}")
            continue
        print(f"status={r.status_code} type={r.headers.get('Content-Type', '')[:40]} bytes={len(r.content)}")
        if r.status_code != 200:
            continue
        if url.endswith("robots.txt") or "json" in r.headers.get("Content-Type", ""):
            print(r.text[:1500])
            continue
        lines = [ln.strip() for ln in text_of(r.text).splitlines() if len(ln.strip()) > 40]
        hits = [ln for ln in lines if KEYWORDS.search(ln)]
        for ln in hits[:40]:
            print("-", ln[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
