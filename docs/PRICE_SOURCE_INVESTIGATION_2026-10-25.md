# Price / candle source investigation — 2026-10-25

Scope: every candidate for U.S. stock prices and candles (EOD, delayed intraday, live).
Each block is classified by **cause** and linked to evidence. Term quotes come from
`data/source_rights.json` (full-text probes), so they are not repeated here. The probes are
GitHub Actions runs 39529567535, 39566940801 and 40173362934; the account-key check is run 39923354151.

## Cause categories

| Code | Meaning |
|---|---|
| `NO_KEY` | The provider needs an account key and none is configured (booleans only were checked, never values). This describes the current setup only; a missing key is **not** evidence that the use is forbidden. |
| `NETWORK` | Technical: timeout, refused from the runner, or the endpoint is down. |
| `LOCAL_POLICY` | Our own precautionary gate (`options_radar/source_permissions.py`). It is closed although no term was confirmed. |
| `CONFIRMED_TERMS` | The provider's own terms or robots.txt forbid the use. The text was read in full or the file was fetched. |
| `TERMS_UNKNOWN` | The terms page could not be read (404/403). A 404 means the check is incomplete, not that the source is blocked: the current official page must be located. Unknown is never treated as permission. |
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
| Massive (Polygon) | NO_KEY + CONFIRMED_TERMS (public) | stocks, options | not probed | 🔑 | ? | 🔑 | ✗ | ✗ | `/legal` gave 404 in run 40173362934 (incomplete). Current page `massive.com/legal/market-data-terms-of-service`, fetched in run 40236507337: market data may not be "publicly displayed … or distributed in any way" without Massive's prior written consent. Derived results: not settled. |
| Tradier | NO_KEY + CONFIRMED_TERMS (public) | U.S. stocks and options; needs a Tradier Brokerage account | sandbox data delayed 15 min | 🔑 | ? | 🔑 personal | ✗ | ✗ | Old terms URL gave 404 (incomplete). Current `docs.tradier.com/docs/faq` (run 40236507337): "Unless you are a Tradier Partner, Tradier APIs are intended for personal use only." |
| IEX HIST | DATA_UNAVAILABLE + TERMS_UNKNOWN | IEX-only ticks, pcap | T+1 | ? | ? | ? | ✗ | ✗ | run 40173362934: T+1 pcap files; the agreement text was truncated and could not be read |
| FRED (SP500, NASDAQCOM) | NETWORK + series copyright | index levels only, daily | 1 day | ? | ? | ? | ? | ? | run 40173362934: ReadTimeout on every page; S&P/Nasdaq index series are third-party copyrighted |
| Nasdaq Data Link | DATA_UNAVAILABLE | no free U.S. equity EOD (WIKI ended 2018) | — | — | — | — | — | — | rights matrix `nasdaq_data_link`: terms unknown |
| Exchange files (NYSE/Nasdaq daily) | DATA_UNAVAILABLE (paid) | — | — | — | — | — | — | — | paid exchange products; nasdaqtrader symbol directory is restricted (rights matrix) |
| Academic (CRSP/WRDS) | DATA_UNAVAILABLE (institutional subscription) | — | — | — | — | — | — | — | not free; not available to this account |
| TradingView widgets | NOT a data source | display in the visitor's browser | provider delay | ✗ | ✗ | ✗ | ✓ widget only | ✗ | rights matrix `tradingview_widgets`: non-display usage prohibited |

Gates that are `LOCAL_POLICY` only: none in the price group. Every closed price gate is backed by
`CONFIRMED_TERMS` (Yahoo, Nasdaq.com, Cboe, Stooq) or by `NO_KEY` plus terms that forbid redistribution.

## Conclusion

**We have not yet verified a free source suitable for feeding our engine and redistributing its outputs
within the required use.** The table shows, per source, which use is confirmed forbidden, which is
permitted for the owner only, and which is still unverified.

Five uses are kept apart, because a source can allow one and forbid another:

| Use | What it means here | Status today |
|---|---|---|
| Embedded official components | TradingView widgets render their own data in the visitor's browser | Allowed and used (PR #387); no data reaches GHAZI |
| Raw data for our computation | GHAZI fetches bars/quotes to compute an analysis | Owner-private only (Alpaca, Tradier personal use) with keys; Yahoo/Nasdaq.com/Stooq forbidden |
| Display of derived results | publishing GHAZI's computed levels/signals | UNVERIFIED for Alpaca and Massive; forbidden for Tradier (personal use only); not published |
| Redistribution of prices | prices on the site or in a shared Telegram chat | Forbidden for every candidate checked; needs a licence |
| Personal vs public | owner's own chat / runner vs site, group, channel | Personal allowed for Alpaca (owner attestation) and Tradier; public not allowed |

`options_radar/output_policy.py` enforces these per (source, use), denying by default.

## Progressive path that remains lawful

| Stage | Source | Status |
|---|---|---|
| (a) Weekly/daily EOD | Alpaca IEX completed daily bars | CODED (`options_radar/alpaca_delayed_research.py`, `scripts/build_daily_plan.py`, PR #381). Owner-private only, written to `$RUNNER_TEMP`, never published. Needs `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` and `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`. |
| (b) Delayed intraday (4H/1H/15m/5m) | Alpaca IEX 5-minute bars, request end held 16 min back | CODED and TESTED with synthetic fixtures (PR #388): 15m/1H/4H built from 5m on XNYS session boundaries; owner-private only. Not yet run live (no key). |
| (c) Live | none qualified | Needs a licensed live feed with structured evidence (V11 gate); none is free. |

## Alpaca investigation (closed as far as public documents allow, 2026-10-26)

Read on the runner in run 40238841187 (official pages only):

| Question | Answer | Evidence |
|---|---|---|
| Historical and recent bars | Basic (free, paper or live account): historical bars since 2016; the only limit is "latest 15 minutes". For SIP: "the `end` parameter must be at least 15 minutes old to query SIP data without a subscription". | docs.alpaca.markets about-market-data-api.md, market-data-faq.md |
| Frames | Minute and daily bars are built from trades; other bars (e.g. 1Hour, 1Week) are aggregated from minute or daily bars. We request 5Min and 1Day and build 15m/1H/4H on XNYS session boundaries ourselves. | market-data-faq.md |
| Coverage | Real time on Basic: IEX only (one exchange). Historical SIP: the consolidated tape ("100% of market volume"), allowed when 15+ minutes old. Snapshots and "latest" endpoints need a subscription for SIP, so ours use IEX and say so. | both pages |
| Missing bars | "the bar is only emitted if none of its fields are 0": no bar means no qualifying trade, not a data fault. | market-data-faq.md |
| Personal use and derived analysis | The Trading API is for individual traders "using Alpaca's trading platform directly". Redistribution: "Unfortunately, you cannot redistribute Alpaca API data." No public text on derived results was found. | alpaca.markets support page |
| Storage, Telegram | Not addressed in the public pages. We keep data only inside the run (no cache, artifact, bot-state or log) and send only to the owner's own private chat after the owner records ALPACA_PRIVATE_ALERTS_AUTHORIZED. | design choice, not a provider statement |
| Needs a subscription | Real-time SIP, the latest 15 minutes of SIP, SIP snapshots, more than 200 historical calls per minute (Algo Trader Plus). | about-market-data-api.md |
| Market Data Agreement | `files.alpaca.markets/disclosures/library/MarketDataAgreement.pdf` answered **HTTP 403** to the runner, so it has **not** been read (an earlier note said it was fetched; that was wrong). It is shown to the account holder at sign-up. | run 40238841187 |
| Screener (most actives / movers) | Not covered by the pages read; the scan does not depend on it. | — |

The owner's `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true` records that the owner read and accepted Alpaca's
agreements for personal use; it is not Alpaca's permission and does not replace reading the agreement.

## Other checks on 2026-10-26

- FDA press-release RSS: every fda.gov URL (feed, robots.txt, website policies) redirected the runner to
  `apology_objects/abuse-detection-apology.html` (run 40238841187). The site's bot protection is not worked
  around (no identity switching or retries), so this faster source is not usable from GitHub runners.
- TradingView (runs 40233630558, 40234894415, 40238841618): the nine cash-index symbols tested
  (SP:SPX, TVC:SPX, NASDAQ:NDX, TVC:NDX, DJ:DJI, TVC:DJI, TVC:RUT, CBOE:VIX, TVC:VIX) did not render in the
  mini-symbol-overview and advanced-chart embeds; ETFs and 26 stock listings did. The finding is limited to
  those symbols and widgets on that date. Stock and ETF quotes in the embeds were labelled "Cboe One".

## SEC access (not a price source, recorded here because it blocks size data)

Run 40236507337 (fallback identity, no `SEC_USER_AGENT` secret): `data.sec.gov` answered 403 "Your Request
Originates from an Undeclared Automated Tool"; `www.sec.gov` answered 403 "Request Rate Threshold
Exceeded". The second is a rate/IP response on shared GitHub runners, so adding `SEC_USER_AGENT` is a
required setup step but not a guarantee that every 403 disappears. The code sends the identity in the
`User-Agent` header (asserted in `tests/test_issuer_sizes.py`), pauses 125 ms between requests (SEC asks for
at most 10 per second) and stops on the first 403/429 instead of retrying.

## Minimal owner action

1. A free Alpaca account, then the secrets `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`, then the repository variable
   `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`. This enables the private plans only, not public display.
2. Public display of prices requires a paid redistribution licence. That decision belongs to the owner and
   cannot be replaced by the owner's approval of a free plan.
