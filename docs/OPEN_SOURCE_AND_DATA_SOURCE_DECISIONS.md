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
| Yahoo (yfinance / yahooquery / chart API) | Candles for charts and research | robots.txt disallows the chart/options endpoints for automated agents. Kept only as a labelled research fallback until a permitted source replaces it. |
| api.nasdaq.com screener / movers | Full-market discovery | robots.txt disallows it. Same status. |
| Cboe CDN delayed options JSON | Model GEX inputs | Allowed by robots.txt; delayed, labelled DELAYED / MODEL_ESTIMATED, never execution-grade. |
| nasdaqtrader SymDir, OCC | Symbol lists, open interest | Allowed. |
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
