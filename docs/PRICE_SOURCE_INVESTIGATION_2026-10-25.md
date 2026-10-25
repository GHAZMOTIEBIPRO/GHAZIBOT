# Price / candle source investigation — 2026-10-25

Scope: every candidate for U.S. stock prices and candles (EOD, delayed intraday, live).
Each block is classified by **cause** and linked to evidence. Term quotes come from
`data/source_rights.json` (full-text probes), so they are not repeated here. The probes are
GitHub Actions runs 39529567535, 39566940801 and 40173362934; the account-key check is run 39923354151.

## Cause categories

| Code | Meaning |
|---|---|
| `NO_KEY` | The provider needs an account key and none is configured (booleans only were checked, never values). |
| `NETWORK` | Technical: timeout, refused from the runner, or the endpoint is down. |
| `LOCAL_POLICY` | Our own precautionary gate (`options_radar/source_permissions.py`). It is closed although no term was confirmed. |
| `CONFIRMED_TERMS` | The provider's own terms or robots.txt forbid the use. The text was read in full or the file was fetched. |
| `TERMS_UNKNOWN` | The terms page could not be read (404/403). Unknown is never treated as permission. |
| `NOT_EXECUTION_GRADE` | Usable for research, but never as live or executable evidence. |
| `DATA_UNAVAILABLE` | No free dataset with the needed coverage or frames exists at this source. |

## Matrix: five uses per source

Limits marked "not probed" were not measured by us. Column key: ✓ allowed · ✗ forbidden · ? unverified, which is treated as ✗ · 🔑 allowed only with an owner key and owner authorization.

| Source | Block cause | Coverage / frames | Delay / history | Fetch | Store | Compute | Public display | Telegram | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Yahoo (yfinance, yahooquery, query1/2) | CONFIRMED_TERMS | all, 1m–1mo | delayed | ✗ | ✗ | ✗ | ✗ | ✗ | rights matrix `yahoo`: "using any automated means…" |
| Nasdaq.com / api.nasdaq.com | CONFIRMED_TERMS | screener, quotes | delayed | ✗ | ✗ | ✗ | ✗ | ✗ | rights matrix `nasdaq_web`. This is Fast Explosion's discovery source. |
| Stooq CSV | CONFIRMED_TERMS (robots.txt) | EOD, intraday | EOD / long | ✗ | ✗ | ✗ | ✗ | ✗ | run 40173362934: `User-agent: * Disallow: /` (only Bingbot and Googlebot allowed) |
| Cboe delayed quote table | CONFIRMED_TERMS | options | 15 min | ✗ | ✗ | ✗ | ✗ | ✗ | rights matrix `cboe_delayed`: auto-extraction prohibited |
| **Alpaca Market Data (free plan)** | NO_KEY (+ no redistribution) | all U.S. stocks; 1m…1D bars | live IEX only; SIP history ≥15 min old | 🔑 | 🔑 internal | 🔑 internal | ✗ | ✗ public; owner-private chat not enabled | Alpaca support: "you cannot redistribute Alpaca API data"; FAQ: "`end` … at least 15 minutes old to query SIP data without a subscription"; run 39923354151: key absent |
| Twelve Data (Basic) | NO_KEY + CONFIRMED_TERMS | stocks, 1m…1mo | delayed (not probed) | 🔑 | 🔑 internal | 🔑 internal | ✗ | ✗ | rights matrix `twelve_data`: "solely for Internal Use" |
| Finnhub (free) | NO_KEY + CONFIRMED_TERMS | quotes, candles (free scope limited) | — | 🔑 | ? | 🔑 personal | ✗ | ✗ | rights matrix `finnhub`: "personal use … can't be used by any business" |
| Alpha Vantage (free) | NO_KEY + CONFIRMED_TERMS | daily, intraday | not probed | 🔑 | ? | 🔑 private | ✗ | ✗ | rights matrix `alpha_vantage`: "private and individual in nature" |
| Tiingo (Starter) | NO_KEY + CONFIRMED_TERMS | EOD, IEX intraday | — | 🔑 | ✗ | 🔑 derived | ✗ | ✗ | rights matrix `tiingo`: "may not write, save, archive…" |
| EODHD (free) | NO_KEY + CONFIRMED_TERMS | EOD | not probed | 🔑 | 🔑 private | 🔑 private | ✗ | ✗ | rights matrix `eodhd`: "private, non-commercial" |
| FMP (free) | NO_KEY | EOD, fundamentals | not probed | 🔑 | ? | ? | ✗ | ✗ | rights matrix `fmp` |
| MarketData.app | NO_KEY + CONFIRMED_TERMS | stocks, options | — | 🔑 | ? | 🔑 personal | ✗ | ✗ | rights matrix `marketdata_app`: "personal non-professional use" |
| Massive (Polygon) | NO_KEY + TERMS_UNKNOWN | stocks, options | not probed | ? | ? | ? | ✗ | ✗ | run 40173362934: `/legal` → 404 |
| Tradier | NO_KEY + TERMS_UNKNOWN | needs brokerage account | — | ? | ? | ? | ✗ | ✗ | rights matrix `tradier`: terms 404 |
| IEX HIST | DATA_UNAVAILABLE + TERMS_UNKNOWN | IEX-only ticks, pcap | T+1 | ? | ? | ? | ✗ | ✗ | run 40173362934: T+1 pcap files; the agreement text was truncated and could not be read |
| FRED (SP500, NASDAQCOM) | NETWORK + series copyright | index levels only, daily | 1 day | ? | ? | ? | ? | ? | run 40173362934: ReadTimeout on every page; S&P/Nasdaq index series are third-party copyrighted |
| Nasdaq Data Link | DATA_UNAVAILABLE | no free U.S. equity EOD (WIKI ended 2018) | — | — | — | — | — | — | rights matrix `nasdaq_data_link`: terms unknown |
| Exchange files (NYSE/Nasdaq daily) | DATA_UNAVAILABLE (paid) | — | — | — | — | — | — | — | paid exchange products; nasdaqtrader symbol directory is restricted (rights matrix) |
| Academic (CRSP/WRDS) | DATA_UNAVAILABLE (institutional subscription) | — | — | — | — | — | — | — | not free; not available to this account |
| TradingView widgets | NOT a data source | display in the visitor's browser | provider delay | ✗ | ✗ | ✗ | ✓ widget only | ✗ | rights matrix `tradingview_widgets`: non-display usage prohibited |

Gates that are `LOCAL_POLICY` only: none in the price group. Every closed price gate is backed by
`CONFIRMED_TERMS` (Yahoo, Nasdaq.com, Cboe, Stooq) or by `NO_KEY` plus terms that forbid redistribution.

## Conclusion: no free public price path

There is no free source that permits **public display** of U.S. stock prices or candles computed by GHAZI.
The table above is the proof. The widget path (TradingView) shows the provider's data in the visitor's
browser; GHAZI does not compute anything from it.

## Progressive path that remains lawful

| Stage | Source | Status |
|---|---|---|
| (a) Weekly/daily EOD | Alpaca IEX completed daily bars | CODED (`options_radar/alpaca_delayed_research.py`, `scripts/build_daily_plan.py`, PR #381). Owner-private only, written to `$RUNNER_TEMP`, never published. Needs `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` and `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`. |
| (b) Delayed intraday (4H/1H/15m/5m) | Alpaca bars ≥15 min old | NOT CODED. The engine (`options_radar/daily_plan.py`) builds 4H from 1H bars, but the fetcher only requests daily bars. |
| (c) Live | none qualified | Needs a licensed live feed with structured evidence (V11 gate); none is free. |

## Minimal owner action

1. A free Alpaca account, then the secrets `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`, then the repository variable
   `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`. This enables the private plans only, not public display.
2. Public display of prices requires a paid redistribution licence. That decision belongs to the owner and
   cannot be replaced by the owner's approval of a free plan.
