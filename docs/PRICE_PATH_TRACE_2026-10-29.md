# What stopped the company price analysis (traced 2026-10-29)

## The old path
- **Source:** Yahoo Finance, read through `yfinance` and `yahooquery` (the hosts `query1`/`query2.finance.yahoo.com`).
- **Labels on its output:**
  - the file said "Yahoo Finance yfinance (unofficial research, may be delayed)";
  - `data_role`: `RESEARCH_ONLY_NOT_LICENSED_EXECUTION`.
- **Output:** the published chart and analysis files (`stock_watch_charts.json`, `liquidity_map.json`, `index_charts`, `index_radar`), plus the company analysis built on them.

## Last good data
- **Commit:** bot-state `a04f76a50`, 2026-10-20 03:53 UTC (`runtime/public/data/stock_watch_charts.json`).
- **Coverage:** 27 symbols; 20 requested, all 20 with valid charts. Among them: AAPL, MSFT, NVDA, AMD, AVGO, TSLA, ORCL, PLTR, MU.
- **Newest daily bar:** 2026-10-19 for 21 of the 27 symbols; 2026-10-16 for the other 6. Intraday bars ran to 2026-10-19/20.

## The change that stopped it
- **Commit:** `c37e0b951` "stop automated Yahoo and Nasdaq.com access the providers' terms forbid" (PR #325, 2026-10-20 14:29 +03:00).
- **The terms, read from the runner (run 39413336941):**
  - Yahoo's Terms of Service forbid collecting data "using any automated means … without our express, prior permission";
  - robots.txt on `query1`/`query2.finance.yahoo.com` is `Disallow: /`.
- **What the gate does:**
  - Every Yahoo transport checks the gate `YAHOO_AUTOMATED_ACCESS_APPROVED` before any request.
  - The public chart files were replaced by `SOURCE_TERMS_BLOCKED` reports, so Yahoo-derived bars would not age on the site.
  - The file is still rewritten as a blocked report: the latest is bot-state `3b48b3ea6`, 2026-10-29 14:12 UTC.

## Why it is not simply re-enabled
- The user's approval is not Yahoo's permission, and nothing has changed in Yahoo's terms.
- `yfinance` and `yahooquery` are the same Yahoo source family. They are not two independent sources.
- OpenBB is an interface to providers. It does not change any provider's terms.

## The lawful replacement and its state
- **Replacement:** Alpaca market data, owner-private (`options_radar/bar_providers.AlpacaBars`).
- **State:** the settings check (run 40854043567, 2026-10-29 10:00 UTC) shows the Alpaca keys and attestation absent, as well as every other price key (Alpha Vantage, Tiingo, Twelve Data, Polygon, Finnhub, Tradier, MarketData, Intrinio).
- **When it is ready for a test run:** after these are set:
  - secrets `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`;
  - variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`.
- **SPX:** Alpaca's stock feed carries SPY and QQQ, not the SPX cash index, so SPX coverage is not promised until it is tested.
