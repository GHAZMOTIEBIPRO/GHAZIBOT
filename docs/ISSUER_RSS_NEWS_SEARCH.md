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
