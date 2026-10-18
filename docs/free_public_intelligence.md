# Free public intelligence bridges — research-only

## What this integrates
- **GDELT DOC 2.0**: one bounded free `artlist` query for a few tracked tickers per scan. Results are *attention only*, with `observed_at` from GDELT (not a verified publication timestamp). The parser requires an explicit `$MU` or `NASDAQ:MU`-style ticker in the headline. Aggregated coverage is neither independent catalyst proof nor a proxy for institutional order flow. Partial/missing matches do not imply no news.
- **Federal Reserve monetary-policy RSS**: official *published* headlines, not the future FOMC decision calendar and not a trade direction.
- **BLS official iCalendar**: official scheduled release times for CPI/PPI/Employment Situation/JOLTS etc. The real economic figure is unknown until released, and rescheduled announcements must be rechecked. UTC timestamps account for U.S. Eastern DST when TZID is provided.
- **Feedparser (BSD-2-Clause)**: RSS parsing only; never downloads untrusted embedded URLs automatically.
- **Alpaca Basic/IEX**: only when existing `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` secrets are configured; checks single-exchange historical minute bar timestamp without presenting it as SIP, OPRA, or an execution-ready quote. No API key is required for the other three public sources.

## Runtime owner
The **existing** `.github/workflows/company-news-watch.yml` (triggered by market orchestrator) creates `free-public-intelligence` artifact. There is no new scheduling workflow and no extra persistent state writer. Its existing company-news Telegram state stores deduplicated BLS reminders. Only *upcoming verified BLS* releases within 90 minutes generate **information-only** notifications; press and GDELT coverage cannot create signals or CALL/PUT.

The public intelligence collector is independent of Telegram credentials and fails soft per external source. If BLS responds with 403 or is unavailable, the JSON reports `DEGRADED` and the macro sender sends **no invented event**. Market news alerts continue on their official existing path. Because company-news state persists via the existing artifact, a notification already delivered is not sent again after success.

## How to audit
```bash
python -m options_radar.free_public_intelligence --output public/data/free_public_intelligence.json --symbols MU,RGC,BNAI,NVDA
python -m scripts.send_free_macro_reminders --help
pytest -q tests/test_free_public_intelligence.py
```

Inspect `schema`, `source_errors`, `gdelt_attention`, `fed_monetary`, `bls_upcoming`, `alpaca_iex`, and `policy`. A READY research context does **not** verify live options or imply Telegram delivery; the generated timestamp is a *local observation of the scan*, never quote freshness. Public-source access and licenses may change.

## Visible GHAZI RADAR news watch (October 2026)

The existing Company News Watch workflow now publishes its already-built
`free_public_intelligence.json` as a **single owned** bot-state file. It
does not create a duplicate scheduler. The website shows only article
headlines with unambiguous ticker tagging, original HTTPS article links
and GDELT **observed_at** time (NOT publication time).

These are explicitly SECONDARY UNCONFIRMED NEWS LEADS, not issuer
press releases, SEC filings, trading recommendations or proof of a
positive catalyst. Missing GDELT results and HTTP 429 cannot be replaced
with invented article links. The SEC issuer filing feed remains separate,
and SEC 403 is reported without misrepresenting the GDELT substitute.
