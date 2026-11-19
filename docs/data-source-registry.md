# Data-source registry (2026-11-17)

This is a single index of every data source GHAZI RADAR uses, gates or has evaluated.
- **Clause-level evidence** stays in the documents it came from, and is linked rather than repeated:
  - `DATA_RIGHTS_MATRIX_2026-10-21.md` (account price APIs, read on runners);
  - `DATA_SOURCES_BY_CATEGORY_2026-10-26.md`;
  - `PRICE_SOURCE_INVESTIGATION_2026-10-25.md`;
  - `FREE_PROVIDER_READINESS_2026-10-31.md`;
  - `IR_NEWS_SOURCES_2026-10-28.md`.
- **Use-by-use rights** are in `provider-license-matrix.md`.
- **The gates that enforce them** are in `options_radar/output_policy.py` and `options_radar/source_permissions.py`.

Rules applied here:
- A free key, a reachable endpoint or a third-party summary is **not** permission to redistribute.
- A field the official text did not answer is `UNKNOWN`.
- New rows from 2026-11-17 come from the provider's own pages found by web search. Third-party summaries are marked
  as such and are not relied on.

**Classification.**

| Class | Meaning |
|---|---|
| `FREE_PUBLIC` | Open terms (public domain, CC0, CC BY, government publication) |
| `FREE_PERSONAL_ONLY` | Free tier limited to personal or non-commercial use |
| `FREE_WITH_LIMITS` | Free with registration, quota or attribution conditions |
| `PAID` | Requires a subscription |
| `LICENSE_RESTRICTED` | Terms forbid our automated or public use |
| `UNAVAILABLE` | The service no longer exists or cannot be reached |
| `UNKNOWN` | Terms not verified |

**Integration status.**

| Status | Meaning |
|---|---|
| `IN_USE` | Feeds a workflow today, with runtime evidence |
| `GATED` | Code exists; closed by a rights gate |
| `CANDIDATE` | Rights look compatible; not built |
| `NOT_PURSUED` | Paid, or terms incompatible |
| `BLOCKED` | Refused at runtime |

## Runtime evidence today (bot-state, 2026-11-17)

| Source | Evidence | Result |
|---|---|---|
| Alpaca (owner-private) | Private Fib `DELIVERED` 15:21:18Z (run 44113187366); shadow `SHADOW_DELIVERED` 21:23:20Z (run 44179152075) | Working, private only |
| NY Fed SOFR / EFFR, OFR (tri-party rate, volume, MMF repo), DOL ETA 539 | `liquidity_monitor.json` 22:53Z: every fetch `OK_HTTP_200` | Working |
| openFDA | `fda_events.json` 21:52Z: 237 approvals, 123 recalls; source updated 2026-11-16 | Working |
| ClinicalTrials.gov | `clinical_registry.json` 21:52Z: `PARTIAL`, 750 records | Working, partial |
| U.S. Treasury yield curve | `public_macro.json` 21:20Z has a curve and no errors; `free_data_health.json` 22:43Z lists it `ok: false` without a status | **Conflict.** The two checks disagree; to investigate |
| GDELT | `free_public_intelligence.json`: 0 rows in all 54 versions from 2026-11-17 13:38Z to 11-18 22:46Z (1 × HTTP 429, then `COOLDOWN_ACTIVE`) | **Not delivering** from shared GitHub runners; the 429 is not worked around |
| TradingView widgets | Site smoke 13:12Z: widget frames render | Display only |
| SEC submissions / Company Facts / EFTS | `free_data_health.json`: HTTP 403 | Blocked (no `SEC_USER_AGENT`); never retried |
| OCC, FINRA Reg SHO, community GEX repos | `SOURCE_TERMS_BLOCKED` | Gated |

**Working authorized providers with evidence today: 8.** They are Alpaca (private), NY Fed, OFR, DOL, openFDA,
ClinicalTrials.gov, GDELT and the TradingView display. The Treasury yield curve is excluded until its health checks
agree.

## Registry

### A. Prices, bars and quotes (account APIs and websites)

| # | Source | Class | Docs / terms | Auth, quota | Redistribution | Delay / timestamps | Status |
|---|---|---|---|---|---|---|---|
| 1 | Alpaca Market Data (stocks) | FREE_WITH_LIMITS | alpaca.markets docs; support: "you cannot redistribute Alpaca API data" | Key; free plan = IEX real time, SIP only ≥15 min old | Denied (raw); derived **UNVERIFIED** | Provider bar timestamps; SIP requests end ≥16 min in the past (`bar_providers.py`) | IN_USE (owner-private) |
| 2 | Alpaca options (indicative feed) | FREE_WITH_LIMITS | as above | Key | Denied | Indicative, never execution-grade | GATED (private research) |
| 3 | Massive (formerly Polygon.io) | PAID | massive.com/legal/market-data-terms-of-service; KB: redistribution needs a "business product" | Key; plans | Business product required; UTP / CME agreements incorporated | Exchange timestamps | NOT_PURSUED |
| 4 | Databento | PAID | databento.com/pricing, /equities | Key, usage-based | Passes through each venue's licence; "Mini" bundle listed without licence fees | Venue timestamps (nanosecond) | CANDIDATE if the owner buys |
| 5 | Tiingo | FREE_PERSONAL_ONLY | app.tiingo.com/tos | Key | Free Starter: no persistent storage, no public derived; Paid: conditional derived | EOD + IEX intraday | GATED (no key) |
| 6 | Finnhub | FREE_PERSONAL_ONLY | finnhub.io/terms-of-service | Key; 30 calls/s cap | "not redistribute … derived results" | — | GATED (no key) |
| 7 | Twelve Data | FREE_WITH_LIMITS | twelvedata.com/terms | Key; per-minute credits | Add-on required | — | GATED (no key) |
| 8 | Alpha Vantage | FREE_PERSONAL_ONLY | alphavantage.co/terms_of_service | Key; 25 requests/day | Commercial / third-party access prohibited | US delayed data needs an entitlement | GATED (no key) |
| 9 | Financial Modeling Prep | FREE_PERSONAL_ONLY | site.financialmodelingprep.com/terms-of-service | Key | Display Licensing Agreement required | — | NOT_PURSUED |
| 10 | EODHD | FREE_PERSONAL_ONLY | eodhd.com/financial-apis/terms-conditions | Key; 20 calls/day | Prohibited | "indicative" free prices | NOT_PURSUED |
| 11 | MarketData.app | FREE_PERSONAL_ONLY | marketdata.app/terms; data-redistribution policy | Key | Self-service plans: personal licence, "redistributing … not permitted"; options display needs an OPRA vendor agreement | — | NOT_PURSUED |
| 12 | Tradier | LICENSE_RESTRICTED | tradier.com/businesses/fintechs; documentation.tradier.com | Brokerage account required | "cannot be redistributed to anyone" without an account | Real time for account holders; sandbox delayed | GATED (no account entitlement) |
| 13 | Intrinio | PAID | help.intrinio.com licensing | Key | Individual plan: no display; Startup: display; redistribution: Enterprise + exchange approvals | — | NOT_PURSUED |
| 14 | Nasdaq Data Link | UNKNOWN | docs.data.nasdaq.com | Key | Per-dataset terms; publisher sets them | Per dataset | UNKNOWN (terms not read) |
| 15 | Schwab Trader API (Individual) | FREE_PERSONAL_ONLY | developer.schwab.com (API terms not read); client agreement: non-professional "personal, non-business use" | Brokerage account + OAuth | Not permitted for non-professionals | Real time for account holder | NOT_PURSUED |
| 16 | IEX Cloud | UNAVAILABLE | Retired 2024-08-31 (IEX Group announcement, reported by migration guides) | — | — | — | — |
| 17 | Yahoo (yfinance, yahooquery) | LICENSE_RESTRICTED | Yahoo ToS; robots `Disallow: /` | — | Prohibited | Unofficial | GATED (`YAHOO_AUTOMATED_ACCESS_APPROVED=false`) |
| 18 | Nasdaq.com / api.nasdaq.com | LICENSE_RESTRICTED | nasdaq.com terms | — | Prohibited | — | GATED |
| 19 | Stooq | LICENSE_RESTRICTED | standing decision (CLAUDE.md) | — | — | — | GATED |
| 20 | TradingView widgets | LICENSE_RESTRICTED (display only) | widget terms | — | Display inside the embed only; never read back | TradingView's own | IN_USE (display) |

### B. Options, volatility and positioning

| # | Source | Class | Docs / terms | Redistribution | Status |
|---|---|---|---|---|---|
| 21 | Cboe delayed quote pages | LICENSE_RESTRICTED | rights matrix | Automated extraction prohibited | GATED (do not re-enable, CLAUDE.md) |
| 22 | Cboe DataShop (historical) | PAID | Historical Market Data Subscriber Agreement; Open-Close page: "internal use only … may not be redistributed"; derived external distribution needs extra fees | Internal only | NOT_PURSUED |
| 23 | OCC market-data pages / batch files | LICENSE_RESTRICTED | occ terms (robots / automated systems prohibited) | Prohibited | GATED |
| 24 | OPRA via any vendor | LICENSE_RESTRICTED | vendor agreements | Display to others needs an OPRA vendor agreement | — |
| 25 | ThetaData | PAID | thetadata.net/subscriber-agreement: "personal, non-commercial use" | Personal only | NOT_PURSUED |
| 26 | ORATS | PAID | orats.com/terms: "own internal business purposes only"; delayed API from $199/month (orats.com llms.txt) | Internal only | NOT_PURSUED |
| 27 | Community GEX archives (GitHub) | LICENSE_RESTRICTED | no licence / unclear upstream | — | GATED |
| 28 | FINRA API (Reg SHO, short interest) | LICENSE_RESTRICTED | FINRA API Terms of Service | Credentials-bound | GATED |

### C. Filings, ownership and identifiers

| # | Source | Class | Docs | Notes | Status |
|---|---|---|---|---|---|
| 29 | SEC EDGAR APIs (data.sec.gov submissions, XBRL) | FREE_PUBLIC | sec.gov developer / fair-access | Declared User-Agent required; 403 from runners without `SEC_USER_AGENT` | BLOCKED |
| 30 | SEC EDGAR full-text search (efts) | FREE_PUBLIC | efts.sec.gov | 403 (identity refused); never retried | BLOCKED |
| 31 | SEC Form 13F Data Sets | FREE_PUBLIC | sec.gov/dera/data/form-13f; readme PDF | Quarterly ZIPs (Feb/May/Aug/Nov runs since 2024); as-filed, flattened; delayed disclosure (45 days after quarter end) | CANDIDATE (Engine E) |
| 32 | SEC Insider Transactions Data Sets (Forms 3/4/5) | FREE_PUBLIC | sec.gov/data-research/sec-markets-data/insider-transactions-data-sets | Quarterly ZIPs; filer-provided, accuracy not guaranteed | CANDIDATE (Engine E) |
| 33 | OpenFIGI | FREE_WITH_LIMITS | openfigi.com/api/documentation | 5 req/min without key, 20/min with key (official docs); terms page dated 2018 | CANDIDATE (symbology) |
| 34 | GLEIF LEI | UNKNOWN | — | Licence not verified this session | UNKNOWN |
| 35 | NasdaqTrader symbol directory | LICENSE_RESTRICTED | nasdaqtrader.com copyright notice | Written consent required | GATED |
| 36 | S&P 500 members (`datasets/s-and-p-500-companies`) | FREE_PUBLIC | ODC-PDDL packaging; Wikipedia CC BY-SA upstream | Current members only | IN_USE (`symbol-directory.yml`) |

### D. Macro, rates and government statistics

| # | Source | Class | Docs | Notes | Status |
|---|---|---|---|---|---|
| 37 | U.S. Treasury yield curve / Fiscal Data | FREE_PUBLIC | home.treasury.gov; fiscaldata.treasury.gov | Public domain | IN_USE (health conflict, see above) |
| 38 | CFTC Traders in Financial Futures | FREE_PUBLIC | cftc.gov | Weekly, Tuesday positions released Friday | IN_USE (`public_macro.json`) |
| 39 | Federal Reserve Board (DDP) | FREE_PUBLIC | federalreserve.gov | "public domain … cite to the Board" | Probe only |
| 40 | NY Fed Markets API (SOFR, EFFR) | FREE_PUBLIC (with notice) | markets.newyorkfed.org | Required notice on every display (`funding_rates.notice`) | IN_USE |
| 41 | OFR Short-term Funding Monitor | FREE_PUBLIC | financialresearch.gov | Credit requested | IN_USE |
| 42 | DOL ETA 539 (unemployment claims) | FREE_PUBLIC | oui.doleta.gov | Not seasonally adjusted; compared with the same week a year earlier | IN_USE |
| 43 | BEA API | FREE_WITH_LIMITS | apps.bea.gov/api user guide | 36-char UserID; third-party guides cite 100 req / 100 MB / 30 errors per minute; terms PDF not read | CANDIDATE |
| 44 | Census Bureau API | FREE_WITH_LIMITS | census.gov/data/developers/terms-of-service.html | Use = acceptance; call limits; attribution rules | CANDIDATE |
| 45 | EIA Open Data API | FREE_WITH_LIMITS | eia.gov/opendata/terms-of-service.php | Registration; no endorsement or logo use; bulk files need no key | CANDIDATE |
| 46 | BLS | UNKNOWN | terms pages 403 from runners | — | GATED (`bls_macro.json`: `SOURCE_TERMS_BLOCKED`) |
| 47 | FRED / ALFRED | LICENSE_RESTRICTED | API terms forbid storing | — | GATED |
| 48 | World Bank API | FREE_PUBLIC | worldbank.org terms of use for datasets: CC BY 4.0 unless labelled otherwise | Attribution format given | CANDIDATE (low relevance) |
| 49 | OECD API | FREE_WITH_LIMITS | OECD Terms and Conditions (2024-03-15): material is OECD IP | Free, may be suspended | NOT_PURSUED |

### E. News, catalysts and attention

| # | Source | Class | Docs | Notes | Status |
|---|---|---|---|---|---|
| 50 | GDELT | FREE_PUBLIC | gdeltproject.org terms | Citation and link | IN_USE (code); no rows since 2026-11-17: HTTP 429 on shared runners (2026-11-19 review) |
| 51 | openFDA | FREE_PUBLIC (CC0) | open.fda.gov | — | IN_USE |
| 52 | ClinicalTrials.gov API v2 | FREE_PUBLIC (ODbL) | clinicaltrials.gov | Attribution | IN_USE |
| 53 | Federal Register API | FREE_PUBLIC | federalregister.gov | Needs a sponsor→ticker review | CANDIDATE |
| 54 | Company IR RSS / press pages | UNKNOWN (per site) | see `IR_NEWS_SOURCES_2026-10-28.md` | Per-site terms | Per site |
| 55 | Google News RSS | LICENSE_RESTRICTED | robots `Disallow: /` | — | GATED |
| 56 | Press wires (PR Newswire, GlobeNewswire, Business Wire) | LICENSE_RESTRICTED | rights matrix | — | GATED |
| 57 | FDA press RSS | UNAVAILABLE | bot-protection page | Not worked around | — |
| 58 | Wikimedia pageviews (AQS) | FREE_PUBLIC (CC0) | doc.wikimedia.org analytics-api | User-Agent required; rate limits revised in 2026 | IN_USE (`wiki-attention.yml` → `wiki_attention.json`, home summary card); policy-format User-Agent since #446: 33/33 articles OK |
| 59 | House Clerk financial disclosures (PTRs) | FREE_PUBLIC (records) | disclosures-clerk.house.gov | PDFs; automated-access terms not found | UNKNOWN — do not automate yet |
| 60 | Senate eFD | UNKNOWN | efdsearch.senate.gov; Ethics instructions include an "Unlawful Use of Reports" section | Terms not read | UNKNOWN — do not automate |

**Counts.**
- 60 sources are registered: 20 prices, 8 options, 8 filings and identifiers, 13 macro, 11 news and attention.
- By class:

  | Class | Count |
  |---|---|
  | FREE_PUBLIC | 18 |
  | FREE_PERSONAL_ONLY | 7 |
  | FREE_WITH_LIMITS | 8 |
  | PAID | 6 |
  | LICENSE_RESTRICTED | 14 |
  | UNAVAILABLE | 2 |
  | UNKNOWN | 5 |

- 8 have runtime evidence of working today.

## Highest-value next steps (licensing first)

1. **SEC access.**
   - What it needs: the owner sets the `SEC_USER_AGENT` secret (name + contact). This is checked in the code
     (2026-11-19):
     - Format: `<application or organisation name> <contact e-mail>`, at most 256 characters.
       - SEC fair-access guidance: "Sample Company Name AdminContact@<sample company domain>.com".
       - Example: `GHAZI RADAR owner@example.com`.
     - Validation: `scripts/verify_free_market_sources.py::probe_sec` requires an address of the form
       `x@y.z`. Without one, the probe reports `NO_CONTACT_USER_AGENT` or `INVALID_USER_AGENT`.
     - Where to set it: GitHub → Settings → Secrets and variables → Actions → Secrets → `SEC_USER_AGENT`.
     - Never put it in a file or a repository variable: variables are readable in logs.
     - No other setting is needed. `official-sec-pulse.yml`, `catalyst-watchlist.yml`, `company-news-watch.yml`
       and the edgartools adapter read this one secret.
     - Pull-request runs never receive it (#455).
     - Fallback today: a `users.noreply.github.com` address, which SEC refuses with 403. That address is not a
       contact.
     - Verify after setting it:
       - `settings-check.yml` reports `sec_edgar` as no longer `NO_CONTACT_USER_AGENT`;
       - `sec_filing_pulse.json` lists filings.
     - SEC may still refuse cloud IP ranges. If it does, the 403 stays recorded and is not worked around.
   - What it unblocks:
     - the submissions and XBRL APIs;
     - the 13F and Form 3/4/5 quarterly data sets (Engine E);
     - catalyst filings.
   - These are public-domain records, so public derived display is allowed.
2. **Lawful bars for the public radar and target learning.**
   - No free source allows public derived price analytics.
   - Options:
     - a paid plan with explicit display or derived rights (Tiingo Paid, Massive business, Databento with venue licences);
     - or keep price-derived research owner-private.
   - This is the owner's purchasing decision.
3. **Treasury health conflict.** `public_macro` and `free_data_health` disagree, and their checks need reconciling.
4. **Symbology.** OpenFIGI (free with limits) could map tickers to FIGI and resolve corporate-action identity. Its 2018
   terms must be read before use.
