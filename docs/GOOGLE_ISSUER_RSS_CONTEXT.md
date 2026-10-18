# Keyless issuer-name news search — quality and limitations

GHAZI RADAR uses Google News **public RSS search URLs** only as an
unofficial fallback for the free Company News Watch; it does NOT scrape
HTML, retrieve article bodies or assert Google is an issuer.

- Only six bounded issuer-specific queries per run. The first seven
  preference symbols are RGC, BNAI, RKLB, IONQ, SOUN, ASTS and RGTI;
  query selection intersects the existing workflow's configured symbols.
- One exact legal issuer name per query. Search results must independently
  match the issuer's full name or an unambiguous curated alias in their
  headline. Ticker alone, e.g. MU, RGC or AI, never matches.
- Published timestamp must be present, in the past, and at most seven
  days old. Store only titles, source-link and timestamps.
- Google RSS article links are restricted to HTTPS news.google.com.
  The original publication is NOT independently verified by this feed.
- All results carry authority=NEWS_SEARCH_ATTENTION_ONLY and
  positive_catalyst_verified=false. Neither probability of gain nor
  options execution readiness is inferred from media mentions.
- HTTP 403 / 429 immediately stops remaining lookups. Other failures
  are explicit source_errors, no aggressive retries.
- This feed MAY return zero results, may be blocked, and is not covered
  by uptime, licensing or completeness guarantees. It is research-only.

Other feeds remain independent: GDELT (previously HTTP 429),
GlobeNewswire (previously HTTP 403), PR Newswire, and SEC EDGAR
(previously HTTP 403) each preserve their own source status.

References: https://news.google.com/rss/search , and
https://github.com/underloam/xnews/blob/main/src/sources/google.urls.ts
(endpoint concept only, no external source code copied).
