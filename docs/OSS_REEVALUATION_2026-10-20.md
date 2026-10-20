# Re-evaluation of the 53 screened open-source projects (2026-10-20)

The wide survey in `OPEN_SOURCE_AND_DATA_SOURCE_DECISIONS.md` passed 53 of
90 repositories (32 PASS, 21 conditional) on licence, activity and fit. That
screen was done before the source gates closed Yahoo, Nasdaq.com, Cboe
delayed quotes and community GEX feeds (#325, #327) and before the rights
matrix (#330) found that **no free price or options provider is verified for
public display**. A library is only as usable as the data it runs on, so the
53 are re-sorted here by what they can do **on data the project is allowed
to use today**.

Rules applied:
- A code licence grants no data rights. Provider SDKs stay blocked until that
  provider's terms are VERIFIED for the use, or the owner records a licence.
- Statistical tooling counts as "ready" only where an authorized input exists
  now (U.S. Treasury, CFTC, openFDA, the project's own operational logs).
  Price-outcome validation (P8) waits for licensed price history; running it
  on Yahoo-derived outcomes would reuse data whose internal use is restricted.
- Test oracles on synthetic inputs need no data rights.
- Nothing is added to requirements without a measurable gap it closes.

## 1. Keep - integrated and compliant (12)

| Project | Licence | Role now |
|---|---|---|
| gerrymanoim/exchange_calendars | Apache-2.0 | Sessions, holidays, DST, early closes |
| xgboosted/pandas-ta-classic | MIT | Indicators; idle for prices while price sources are gated |
| joshyattridge/smart-money-concepts | MIT | Structure labels; idle for prices while gated |
| TA-Lib/ta-lib-python | BSD-2 | Indicator reference; idle for prices while gated |
| tradingview/lightweight-charts | Apache-2.0 | Site charts with attribution; public price display uses the TradingView widget |
| vollib/py_vollib | MIT | Black-Scholes Greeks (model values, labelled MODEL) |
| vollib/py_lets_be_rational | MIT (setup.py only) | Transitive dependency of py_vollib |
| marcdemers/py_vollib_vectorized | MIT | Stale since 2021-02; replace when the options engine is next touched |
| CarloLepelaars/blackscholes | MIT | Test-only Greeks oracle; found the zomma bug fixed in #315 |
| kurtmckee/feedparser | BSD-2 | Official RSS (Fed, BLS releases, issuer feeds) |
| FDA/openfda | CC0 | Not imported; the openFDA API is integrated directly (#331, #332, #334) |
| ranaroussi/quantstats | Apache-2.0 | Shadow performance reports on the project's own outcome logs |

## 2. Ready now on authorized official data (3)

| Project | Licence | Next use | Authorized input |
|---|---|---|---|
| statsmodels/statsmodels | BSD-3 | HAC (Newey-West) t-statistics and Markov switching for macro context | Treasury par curve, CFTC TFF positioning |
| deepcharles/ruptures | BSD-2 | Change points in the yield curve and in index-futures positioning | same |
| hmmlearn/hmmlearn | BSD-3 (about 2 years idle) | Only if ruptures + statsmodels leave a gap | same |

These describe regimes; they do not produce price directions or probabilities.

## 3. Validation tooling waiting for licensed price data (7)

| Project | Licence | Purpose once licensed history exists |
|---|---|---|
| bashtage/arch | NCSA | SPA / StepM / MCS so stage-rule variants are compared without data snooping |
| skfolio/skfolio | BSD-3 | Purged, embargoed combinatorial CV for the walk-forward harness |
| stefan-jansen/alphalens-reloaded | Apache-2.0 | Descriptive IC and decay of radar scores (association, not probability) |
| baobach/mlfinpy | MIT (small project) | Triple-barrier labels aligned with T1/T2/T3 plus stop |
| lballabio/QuantLib-SWIG | BSD-3 | Shadow American-exercise Greeks on licensed single-name chains |
| nardew/talipp | MIT | Incremental indicators for a licensed stream overlay, with batch-parity tests |
| facioquo/stock-indicators-python | Apache-2.0 (.NET) | Second indicator oracle; heavy runtime, tests only |

## 4. Data-provider SDKs blocked by data rights (11)

| Project | Licence | Why blocked |
|---|---|---|
| ranaroussi/yfinance | Apache-2.0 | Yahoo terms restrict automated access; gated (`YAHOO_AUTOMATED_ACCESS_APPROVED`) |
| alpacahq/alpaca-py | Apache-2.0 | Alpaca rights UNKNOWN (agreement PDF unreadable); public display restricted |
| massive-com/client-python | MIT | Rights mostly UNKNOWN; free tier end-of-day only |
| hydrosquall/tiingo-python | MIT | Free tier: internal/transient only, no storage or redistribution |
| Finnhub-Stock-API/finnhub-python | Apache-2.0 | Public display restricted |
| alexgolec/schwab-py | MIT | Account-holder use only; non-professional exchange rules |
| tastyware/tastytrade | MIT | Account-holder use only |
| pydata/pandas-datareader | BSD-3 | Rights follow each source; several readers defunct |
| OpenBB-finance/OpenBB | Apache-2.0 | Data still comes from providers with their own terms |
| JerBouma/FinanceDatabase | MIT (code) | Data compiled from Nasdaq Trader and others; data rights unclear |
| mortada/fredapi | Apache-2.0 | FRED rights UNKNOWN; reportedly restricts ML/AI training on its content |

Unblocking any of these is an owner action: a licence or written permission,
then `DATA_TERMS_CONFIRMED` and the provider key. No paid plan is assumed.

## 5. SEC tooling blocked on `SEC_USER_AGENT` (6)

| Project | Licence | Note |
|---|---|---|
| dgunning/edgartools | MIT | Preferred: 8-K items, Form 4, XBRL dei shares outstanding / public float |
| HansjoergW/sec-fincancial-statement-data-set | Apache-2.0 | Offline quarterly Financial Statement data sets |
| jadchaar/sec-cik-mapper | MIT | Ticker to CIK; would also widen FDA sponsor-to-ticker matching |
| john-friedman/datamule-python | MIT | Keyed/paid cloud parts unverified; SEC-direct parts only |
| jadchaar/sec-edgar-downloader | MIT | Redundant with edgartools |
| sec-edgar/sec-edgar | Apache-2.0 | Redundant with edgartools |

SEC answers 403 "Undeclared Automated Tool" to the runner until a real
contact User-Agent is configured.

## 6. Not integrating (14)

| Project | Licence | Reason |
|---|---|---|
| rsheftel/pandas_market_calendars | MIT | Redundant with exchange_calendars |
| bukosabino/ta | MIT | Redundant indicators |
| jealous/stockstats | BSD-3 | Redundant indicators |
| pmorissette/bt | MIT | Portfolio backtests; out of scope |
| stefan-jansen/empyrical-reloaded | Apache-2.0 | Overlaps quantstats |
| stefan-jansen/pyfolio-reloaded | Apache-2.0 | Overlaps quantstats |
| robertmartin8/PyPortfolioOpt | MIT | Portfolio optimisation; out of scope |
| polakowo/vectorbt | Apache-2.0 + Commons Clause | Not OSI; research only, not core |
| stefan-jansen/zipline-reloaded | Apache-2.0 | Heavy data bundles |
| ProsusAI/finBERT | Apache-2.0 code | Weights/training-data licence unverified; heavy on Actions |
| GregoryMorse/trendln | MIT | Few tests; trendlines are a price-data feature anyway |
| neurotrader888/TechnicalAnalysisAutomation | MIT | Concepts only; stale |
| bennycode/trading-signals | MIT | Client-side only; the backend stays the source of truth |
| VladPetrariu/Qullamaggie-breakout-scanner | MIT | Concepts only (ADR%, momentum rank, tightness); runs on yfinance |

Total: 12 + 3 + 7 + 11 + 6 + 14 = 53.

## What changed versus the first screen

- Everything that needs prices moved behind data rights (categories 3 and 4).
- The only new integrations since the screen run on verified data: openFDA
  (CC0) for regulatory events and alerts, U.S. Treasury and CFTC for macro
  context.
- Indicator libraries stay installed but have no authorized production price
  input until a licensed source exists.
