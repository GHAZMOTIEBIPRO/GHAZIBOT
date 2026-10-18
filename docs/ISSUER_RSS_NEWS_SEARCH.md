# GHAZI RADAR — precise, bounded Google News RSS research fallback

Why: On 2026-10-18 real GitHub runners reported GDELT HTTP 429,
SEC submissions HTTP 403, public GlobeNewswire RSS HTTP 403, and
PRNewswire RSS offered zero issuer-related titles in the fetched window.
CI jobs succeeding is not evidence of usable company-news coverage.

An additional research-only lane now searches the **Google News RSS search
feed** by a short curated *full issuer name*, for at most six small-cap
issuers per run (RGC, BNAI, RKLB, IONQ, SOUN, ASTS). It is an unofficial
RSS endpoint, not a documented Google News API or licensed real-time
financial-news product; it can change, throttle or cease to work.

Safeguards:
- The actual news headline MUST contain a vetted full or unambiguous issuer
  name, not simply a stock ticker, industry word or matching query.
- Only https://news.google.com links and parsed source publication times
  from within seven days are retained. Search queries have fixed limit,
  timeouts and no retry loops. Output limited to 36 links.
- The item is an **aggregator discovery link**: not authenticated issuer
  release, independent confirmation, SEC filing, bullish catalyst, price
  signal or option market data.
- A feed error or zero matching articles must be reported as such,
  never silently copied from last month's cache or invented.
- Display only the original RSS title and link, not article bodies.
- If RSS is unavailable or platform rate limits are breached, disable this
  adapter and keep the rest of the radar operational.

Reference URLs:
https://news.google.com/rss/search?q=Rocket%20Lab%20stock&hl=en-US&gl=US&ceid=US:en
https://github.com/underloam/xnews/blob/main/src/sources/google.urls.ts

## Precision filter after first real ingestion

The first successful 2026-10-18 GitHub runner collected 36 company-name
matching Google News headlines, but a manual sample showed generic Yahoo
quote portal pages and opinion-only “Buy/Sell/Hold” articles. These are not
company catalysts. The feed now removes stock quote/forecast portals and
headlines without a named company event; it caps research stories at four
per issuer so RKLB cannot overwhelm the feed. A possible loss, delay, or
financing risk is labeled for review instead of treated as positive news.

This is a **keyword-based topic filter**, not issuer authentication, complete
coverage, semantic event classification, accurate sentiment, or a calibrated
win probability. It can miss headlines that use unfamiliar event wording;
that tradeoff is intentional to prioritize relevance over volume.
