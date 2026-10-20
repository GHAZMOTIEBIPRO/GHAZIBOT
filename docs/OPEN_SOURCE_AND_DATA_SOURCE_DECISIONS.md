# Open-source and data-source decisions (2026-10-20)

Licenses were read from each repository's LICENSE file on 2026-10-20.
"Adopt" means a real improvement over what already exists; nothing is added
just because it is popular.

## Libraries

| Project | License (verified) | Decision | Reason |
|---|---|---|---|
| tradingview/lightweight-charts | Apache-2.0 | Keep (already integrated) | Used by the terminal and legacy chart with `attributionLogo: true` and a visible TradingView link. |
| vollib/py_vollib | MIT | Not added | The engine's Black-Scholes gamma is now checked against the gamma Cboe publishes per contract (`greek_check`), which needs no new dependency. Revisit if IV solving from prices is needed. |
| dgunning/edgartools | MIT | Deferred | Useful to parse 8-K items / Form 4 once SEC access works; blocked until `SEC_USER_AGENT` with a real contact email exists. |
| bfolkens/py-market-profile | BSD | Not added | `options_radar/volume_liquidity.py` already computes POC/VAH/VAL from OHLCV with disclosed bins; no gap it fills. |
| TA-Lib/ta-lib-python | BSD-2-Clause | Not added | Needs the C library; existing RSI/ATR already match Wilder references (RSI <= 0.03, ATR <= 0.02%). |
| polakowo/vectorbt | Apache-2.0 + Commons Clause | Not added | Commons Clause restricts selling; the walk-forward and stage evaluators already cover the needed backtests. |
| OpenBB-finance/OpenBB | Apache-2.0 | Not added | Large dependency; its market data still comes from providers with their own keys and terms, so it does not solve licensing. |

## Wide GitHub survey (2026-10-20)

97 items evaluated (90 repositories, 7 data sources) across market data,
technical analysis, options, news/filings, quant research and screeners.
Licenses were read from each LICENSE file; last activity from a shallow
clone of the default branch. 53 repositories passed screening (32 pass,
21 conditional); 37 failed.

Integrated so far, each because it fixed or measured something real:

| Project | License | Use | Result |
|---|---|---|---|
| CarloLepelaars/blackscholes | MIT | Test-only oracle for the engine's Greeks (`tests/test_greeks_reference.py`) | Found the zomma formula off by 1/(sigma*T) (x3,333 short-dated); fixed in #315. |
| Cboe per-contract gamma (data, not a library) | n/a | `greek_check` A/B of the engine's clock | Calendar-to-settlement clock: median drift 2.4% vs 6.8%, p90 26% vs 161% (#311). |

Ranked next candidates (permissive, maintained, adds a measurable capability):

1. skfolio (BSD-3) - purged/embargoed combinatorial CV for the walk-forward harness.
2. arch (NCSA) - SPA / StepM / MCS tests so stage-rule variants are compared without data snooping.
3. alphalens-reloaded (Apache-2.0) - descriptive IC and decay of radar scores (association, not probability).
4. QuantLib (BSD-3) - American-exercise Greeks for single-name contracts (shadow check of European values).
5. talipp (MIT) - incremental indicators for the stream overlay with batch-parity tests.
6. ruptures (BSD-2) + statsmodels (BSD-3) - volatility/RVOL regime breaks and HAC t-statistics.
7. edgartools / secfsdstools - filing-dated shares outstanding and public float (blocked until SEC_USER_AGENT).
8. FinanceDatabase (MIT) - sector/industry mapping for sector-relative strength (internal use only).

Rejected for core: GPL/AGPL/LGPL (optionlab is now GPL-3.0, FinancePy,
backtrader, backtesting.py, gammagrid, edgar-crawler, pypbo, finta,
tulipy, nautilus_trader, MibianLib); no license (pandas-ta original repo
is gone, chart_patterns, gex-tracker); non-commercial (PatternPy,
mlfinlab); scrapers whose sources forbid automation (TradingView-Screener,
tvdatafeed, finviz, finvizfinance).

Existing-stack findings: `py_vollib_vectorized` in requirements-research.txt
has had no commit or release since 2021-02; `py_lets_be_rational` ships no
LICENSE file (MIT only in setup.py); FRED's terms reportedly restrict
training ML/AI systems on its content, to be checked before any learning
module uses FRED series.

## Market data used automatically

| Source | Current use | Status |
|---|---|---|
| Yahoo (yfinance / yahooquery / chart API) | Candles, chains, news, statements, profiles | **Gated off (2026-10-20)** after reading the full Terms of Service (see below). Every call site calls `source_permissions.require("yahoo")`; public chart files are replaced by `SOURCE_TERMS_BLOCKED` reports and the site opens the TradingView widget instead. Re-enable with `YAHOO_AUTOMATED_ACCESS_APPROVED=true` only after Yahoo's written permission. |
| api.nasdaq.com screener / movers | Full-market discovery | **Gated off (2026-10-20)** after reading the full nasdaq.com terms. Re-enable with `NASDAQ_WEB_AUTOMATION_APPROVED=true` only after Nasdaq's written permission. |
| Cboe CDN delayed options JSON | Model GEX inputs, option analytics | **Gated off (2026-10-20).** robots.txt does not forbid it, but Cboe's delayed-quote pages prohibit auto-extraction of delayed quote table data, and Cboe's data policies treat single-security, price-like derived data as fee liable. Re-enable with `CBOE_DELAYED_AUTOMATION_APPROVED=true` only after a Cboe DataShop licence or written permission. |
| nasdaqtrader SymDir and halt RSS, OCC | Symbol lists, halts, open interest | Still running. nasdaqtrader.com is a separate site; its terms were not readable by the probe (page rendered without terms text) and must be confirmed. |
| CFTC Traders in Financial Futures + U.S. Treasury par yield curve | Index-futures positioning (ES, NQ, RTY, YM, VX) and rate backdrop (`public_macro.json`) | U.S. government publications, no automated-access restriction. Weekly / daily context only. |
| TradingView widgets | Public price display (ticker tape, market overview) | Embedded with TradingView branding; data is not redistributed by this project. |

### Why Yahoo was not simply swapped for Alpaca or Tiingo

The public site publishes candle bars (`stock_watch_charts.json`). Free
Alpaca (IEX) and Tiingo accounts are intended for the account holder's own
use; publishing their bars on a public website would be redistribution,
which their standard terms do not grant without a separate license. Swapping
sources would replace one terms problem with another. A compliant design is:

1. Internal analysis (levels, RVOL, decisions) from an account-authorized
   feed, with only derived research published, never raw bars.
2. Public price charts through an embed whose provider licenses public
   display (for example a TradingView chart widget), after the owner
   confirms that provider's current widget terms.

Both steps need the owner: account keys plus a written confirmation of the
provider's terms for this use. Until then nothing is switched silently.

## Full official documents read (GitHub runner, run 39413336941, 2026-10-20 11:12Z)

`scripts/probe_terms.py` fetched each provider's own page from a GitHub
runner (the build sandbox cannot reach them) and printed the clauses on
automated access, storage and redistribution. Verbatim extracts:

- **Yahoo Terms of Service** (legal.yahoo.com/us/en/yahoo/terms/otos): you
  must not "access or collect data, or attempt to access or collect data,
  from our Services using any automated means, devices, programs,
  algorithms or methodologies, including but not limited to robots,
  spiders, scrapers, data mining tools, or data gathering or extraction
  tools, for any purpose without our express, prior permission"; and
  "Unless otherwise expressly stated, you may not access or reuse the
  Services, or any portion thereof, for any commercial purpose".
  `query1.finance.yahoo.com/robots.txt` and `query2.../robots.txt`:
  `User-agent: * / Disallow: /`. **Verdict: current use not permitted;
  stopped.**
- **Nasdaq.com terms** (nasdaq.com/legal): licence "solely for your
  personal, non-commercial use"; you agree to "Not access or use the
  Service, or any process, whether automated or manual, to capture data or
  content from the Service". `api.nasdaq.com/robots.txt`: `Disallow: /`.
  **Verdict: not permitted; stopped.**
- **Cboe delayed quotes page**: "IT IS STRICTLY PROHIBITED TO DOWNLOAD
  DELAYED QUOTE TABLE DATA FROM THIS WEB SITE BY USING AUTO-EXTRACTION
  PROGRAMS/QUERIES AND/OR SOFTWARE ... DOWNLOADING THIS DATA IN ANY OTHER
  WAY THAN BY MANUAL TICKER SYMBOL ENTRY IS STRICTLY PROHIBITED."
  **Verdict: stays gated off.**
- **Alpaca support**: "Unfortunately, you cannot redistribute Alpaca API
  data." Internal use by the account holder only; not configured
  (no keys).
- **Tiingo Terms of Use** §1.6: on non-enterprise plans "you may not
  write, save, archive, back up, or otherwise retain Tiingo Data in any
  persistent or durable storage", and "A Starter Plan or Trial Plan does
  not permit persistent storage of Derived Products". Public tables,
  charts or dashboards that display Tiingo data are listed as prohibited
  derived products. **Verdict: the free plan cannot feed this project's
  stored, published pipeline.**
- **CFTC Public Reporting (Socrata API)** and **U.S. Treasury yield curve**:
  open U.S. government data, reachable without keys; used as legal
  replacements for macro and positioning context.

## Terms by use type (2026-10-20)

| Provider | Internal automated | Non-display | Public raw | Public derived | Real-time display |
|---|---|---|---|---|---|
| Cboe delayed quotes | prohibited (auto-extraction) | licence (2026 non-display categories) | not permitted | single-security price-like derived data generally fee liable | n/a |
| OPRA | via licensed vendor | fees may apply | vendor agreement even when delayed | unclear | licence + fees |
| Yahoo | prohibited without permission | prohibited | prohibited | unclear (collection itself unauthorised) | prohibited |
| Nasdaq website / API | personal non-commercial only | licence | prohibited | licence holders only | licence |
| Alpaca Basic (IEX) | allowed for the account holder | account holder only | prohibited without written consent | unclear | prohibited |
| IEX (policy Jan 2022) | delayed free | delayed free | delayed free only via a subscriber that allows it | allowed free for derived data | agreement |
| Tiingo free | personal/internal; no persistent storage on free plans | internal | prohibited | unclear | redistribution licence |
| TradingView widgets | n/a (no data access) | n/a | n/a | n/a | allowed inside the widget with branding kept |

Consequences applied: Cboe, Yahoo and Nasdaq-website automated reads are
gated off by default (`options_radar/source_permissions.py`, test
`tests/test_yahoo_nasdaq_gates.py` fails if a new Yahoo/Nasdaq caller skips
its gate). Public price display moved to the TradingView widget. Owner-only
decisions: requesting permission or licences (Yahoo, Nasdaq, Cboe DataShop,
OPRA vendor, Alpaca/IEX consent for derived publication); adding an Alpaca
account for internal-only analysis; confirming nasdaqtrader.com terms.
