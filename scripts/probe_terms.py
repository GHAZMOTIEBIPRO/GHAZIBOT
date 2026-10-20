"""Diagnostic: fetch providers' official terms pages and print the clauses
about automated access, storage, redistribution and display. Read-only;
it reads terms pages and robots.txt only, never market data."""
from __future__ import annotations

import html
import io
import re
import sys

import requests

PAGES = {
    # Already reviewed in full (2026-10-20, run 39413336941); kept for re-checks.
    "yahoo_tos": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    "yahoo_query1_robots": "https://query1.finance.yahoo.com/robots.txt",
    "nasdaq_legal": "https://www.nasdaq.com/legal",
    "nasdaq_api_robots": "https://api.nasdaq.com/robots.txt",
    "cboe_delayed_quotes": "https://www.cboe.com/delayed_quotes/spx/quote_table",
    "tiingo_tos": "https://app.tiingo.com/tos/",
    "alpaca_redistribute": "https://alpaca.markets/support/redistribute-alpaca-api",
    # Price / options candidates for the rights matrix.
    "alpaca_terms": "https://alpaca.markets/terms",
    "alpaca_market_data_agreement": "https://files.alpaca.markets/disclosures/library/MarketDataAgreement.pdf",
    "finnhub_terms": "https://finnhub.io/terms-of-service",
    "twelvedata_terms": "https://twelvedata.com/terms",
    "polygon_terms": "https://polygon.io/terms",
    "massive_terms": "https://massive.com/terms",
    "alphavantage_terms": "https://www.alphavantage.co/terms_of_service/",
    "fmp_terms": "https://site.financialmodelingprep.com/terms-of-service",
    "eodhd_terms": "https://eodhd.com/financial-apis/terms-conditions",
    "tradier_terms": "https://tradier.com/terms-of-service",
    "marketdata_terms": "https://www.marketdata.app/terms/",
    "nasdaq_data_link_terms": "https://data.nasdaq.com/terms",
    "iex_market_data_policy": "https://www.iexexchange.io/market-data",
    "nasdaqtrader_symdir": "https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs",
    "nasdaqtrader_terms": "https://www.nasdaqtrader.com/Trader.aspx?id=TermsOfUse",
    "tradingview_widget_terms": "https://www.tradingview.com/widget-docs/",
    "tradingview_policies": "https://www.tradingview.com/policies/",
    # Government / official.
    "sec_edgar_access": "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data",
    "sec_privacy_security": "https://www.sec.gov/privacy",
    "fred_api_terms": "https://fred.stlouisfed.org/docs/api/terms_of_use.html",
    "fred_legal": "https://fred.stlouisfed.org/legal/",
    "bls_api_terms": "https://www.bls.gov/developers/termsOfService.htm",
    "bea_api_terms": "https://apps.bea.gov/api/_pdf/bea_api_tos.pdf",
    "census_api_terms": "https://www.census.gov/data/developers/about/terms-of-service.html",
    "openfda_terms": "https://open.fda.gov/terms/",
    "finra_api_terms": "https://developer.finra.org/terms-of-service",
    "treasury_fiscaldata": "https://fiscaldata.treasury.gov/api-documentation/",
    "cftc_public_reporting": "https://publicreporting.cftc.gov/stories/s/r4w3-av2u",
    "federalreserve_data": "https://www.federalreserve.gov/data.htm",
    "occ_market_data": "https://www.theocc.com/market-data/market-data-reports",
}
KEYWORDS = re.compile(r"(automat|scrap|robot|spider|crawl|redistribut|personal|non-?commercial|"
                      r"commercial|display|derived|extract|reproduc|permission|licen[cs]e|"
                      r"internal|store|storage|retain|cache|third[- ]part|public|website|disallow|"
                      r"user-agent|rate limit|attribution|public domain)", re.IGNORECASE)
UA = {"User-Agent": "Mozilla/5.0 (compatible; GHAZI-terms-review/1.1; research)"}
MAX_LINES = 45


def text_of(body: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<[^>]+>", "\n", body)
    return html.unescape(re.sub(r"[ \t\r\f\v]+", " ", body))


def pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:40])


def main(only: list[str]) -> int:
    for name, url in PAGES.items():
        if only and name not in only:
            continue
        print(f"\n===== {name} | {url}")
        try:
            r = requests.get(url, headers=UA, timeout=25)
        except requests.RequestException as exc:
            print(f"FETCH_ERROR {type(exc).__name__}")
            continue
        kind = r.headers.get("Content-Type", "")
        print(f"status={r.status_code} type={kind[:40]} bytes={len(r.content)} final_url={r.url[:120]}")
        if r.status_code != 200:
            continue
        if url.endswith("robots.txt") or "json" in kind:
            print(r.text[:1500])
            continue
        body = pdf_text(r.content) if "pdf" in kind or url.endswith(".pdf") else text_of(r.text)
        lines = [ln.strip() for ln in re.split(r"\n|(?<=[.;])\s{2,}", body) if len(ln.strip()) > 40]
        hits = [ln for ln in lines if KEYWORDS.search(ln)]
        for ln in hits[:MAX_LINES]:
            print("-", ln[:700])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
