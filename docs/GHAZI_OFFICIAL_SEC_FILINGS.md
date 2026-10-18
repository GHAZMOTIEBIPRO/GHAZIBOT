# GHAZI RADAR: free official issuer-filing feed

This module uses **SEC EDGAR official** ticker/CIK mapping and recent
issuer submissions, then links directly to the original filing.
No API key or broker is required. The shared GitHub-hosted collector
runs a bounded 24-issuer pass three times per weekday, as a distinct
writer to its single bot-state destination.

## Evidence meaning

- Official CIK and accession identities are verified.
- A form 8-K or 6-K is a **material-event review**, not confirmed positive
  catalyst, customer contract win, forecast change, or 100% rise.
- S-1, S-3, F-3, S-4, 424B2 and 424B5 are **offering/dilution review** risks.
- 10-Q/10-K are periodic reports; direction needs financial analysis.
- Filings lacking a trustworthy accession/primary document are discarded.
- SEC blocking, 429 and 403 are exposed as unavailable/partial data.
- Data has a generated timestamp separate from filing date.
- The site's issuer feed is intentionally research-only, not price/OPRA quotes.

## Sources and restrictions

https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

SEC requests include a descriptive contact User-Agent; calls are
sequential and no faster than approximately 2.5/s. No aggressive retrying
on 403 or 429, no scraping SEC HTML and no unlicensed quote redistribution.
Filings are not a universal news feed: some company press releases and
large moves may never appear here. Low-cost GDELT is context, not primary
filing confirmation.

If the public SEC service blocks shared CI runners, the report must explicitly
show UNAVAILABLE instead of inventing documents or bullish outcomes.

## Blocked official ticker-map mitigation (2026-10-18)

GitHub hosted runners returned HTTP 403 for the primary SEC ticker/CIK map.
As an optional *lookup candidate only*, the system uses the MIT-licensed
jadchaar/sec-cik-mapper SEC-derived ticker file, last publicly updated
2025-02-28. **It is stale and not accepted as issuer proof**. Filings may be
published only if fresh data.sec.gov submissions return the expected CIK
**and** explicitly list the nominated ticker in their own tickers array.
The issuer name comes from that fresh SEC response, not the mirror.
If data.sec.gov also returns HTTP 403, status remains UNAVAILABLE and no
filings are fabricated. This is not an exchange licensed market feed.

Mapping URL:
https://github.com/jadchaar/sec-cik-mapper/blob/main/mappings/stocks/ticker_to_cik.json
