# Data rights matrix: clauses, not summaries (2026-10-21)

The machine-readable matrix is `data/source_rights.json`. The gates are in
`options_radar/source_permissions.py` (automated access),
`scripts/price_source_gate.py` (internal vs public use of a key) and
`options_radar/public_guard.py` (public outputs).

**Evidence.** Each page was read from a GitHub runner, using terms and pricing
pages only:
- run 39413336941: Yahoo, Nasdaq.com;
- runs 39478127523, 39521600490, 39522604250, 39523530990: government and news sources;
- run 39529567535: full text of the account-API terms and pricing pages.

Quotes are copied exactly from the fetched text. `[...]` marks a cut. Where
the page lost words when its HTML was stripped, the quote keeps the gap.

**Status values.**
- **VERIFIED**: the text allows the use.
- **RESTRICTED**: the text forbids it, or requires an add-on or a written agreement.
- **UNKNOWN**: the text does not clearly allow it.

The absence of a prohibition is not treated as permission. UNKNOWN counts
only after the owner confirms the plan's terms (`DATA_TERMS_CONFIRMED` /
`PUBLIC_DISPLAY_TERMS_CONFIRMED`). RESTRICTED cannot be opened by the
owner's confirmation: it needs the provider's written permission.

**Telegram.** A message to a group or channel provides the content to third
parties. It therefore follows the same right as public display.

## 1. Account price APIs (no key is configured today)

### Twelve Data — https://twelvedata.com/terms
| Use | Status | Clause |
|---|---|---|
| Internal analysis | VERIFIED | "(a) Access, receive, process, and store Data solely for Internal Use (or as otherwise permitted by your Subscription Tier or add-ons)" |
| Commercial use of the free tier | RESTRICTED | "(l) Use Free Tier data for commercial purposes" (in the "shall not" list) |
| Storage / cache | RESTRICTED beyond the documented periods | "(g) Store or cache Data beyond permitted timeframes specified in the Documentation" |
| Public raw prices | RESTRICTED | "(e) Redistribute or provide external display of Data only if and as expressly authorized by a Redistribution Rights Add-On or separate written agreement with Twelve Data" |
| Derived data, internal | VERIFIED | "(c) Create Derived Data that cannot be reverse-engineered to recreate the original Data"; "Customer retains rights to Derived Data created in compliance with this Agreement." |
| Derived data, public | RESTRICTED | "(g) Create derivative works for redistribution" (in a prohibited list) |
| Telegram | RESTRICTED | Redistribution is "any publication, distribution, or provision of Data to third parties." |

**Plan limits.** The pricing page says "API credits reset each minute. Each
endpoint or subscription has a specific credit weight per symbol". The plan
table is rendered by JavaScript, so the per-plan numbers are read from the
Markdown pricing page (see `docs/TWELVE_DATA_READINESS.md`).

### Finnhub — https://finnhub.io/terms-of-service
- **Internal analysis: VERIFIED (personal use only).** "All plan listed on Finnhub website is [...] personal use unless explicitly stated otherwise. Personal plan can't be used by any business".
- **Public raw, public derived and Telegram: RESTRICTED.** "You hereby agree to not redistribute or share access to data or derived results from the data obtained [...] anyone or any 3rd party without written approval from Finnhub."
- **Storage.** "All data must be deleted should your subscription to that data ends."
- **Limits.** "There is a 30 API calls/second limit on top of all plan's limit".

### Alpha Vantage — https://www.alphavantage.co/terms_of_service/ (PDF)
- **Internal analysis: VERIFIED.** The grant is personal and non-commercial. Commercial use is use that "goes beyond investment analysis, research, testing, monitoring, and any other activities that are private and individual in nature".
- **Public raw, public derived and Telegram: RESTRICTED.** Commercial use includes use "as part of any type of commercial activity that allows individuals or entities other than User to access information directly or [indirectly]".
- **Free plan.** "(25 API requests per day)". Realtime data, 15-minute delayed US data and options data need an entitlement.

### Financial Modeling Prep — https://site.financialmodelingprep.com/terms-of-service
- **Licence: RESTRICTED for this project.** "This license may only be used by a Customer who is an individual, and strictly for their own personal, non-business and non-commercial purposes."
- **Public and Telegram: RESTRICTED.**
  - "Without a specific agreement with FMP, customers are prohibited from showcasing FMP Services or Data on platforms including but not limited to websites, blogs".
  - "data or information contained in or derived from The Services, to any third party".
  - Pricing page: "Displaying or redistributing data sourced from FMP requires a specific Data Display and Licensing Agreement with FMP."

### EODHD — https://eodhd.com/financial-apis/terms-conditions
- **Internal analysis: VERIFIED.** "Non-Professional Users are permitted to store, manipulate, and analyze the data for private, non-commercial purposes."
- **Public and Telegram: RESTRICTED.**
  - "Selling, reselling, retransmitting, redistributing, displaying, or granting access to the Information or Services, whether in its original or repackaged form."
  - "Sharing access to their account with others, including within groups."
- **Free plan.** "Once you register you get 20 free API calls per day." Its prices are "indicative and not appropriate for trading purposes."

### Tiingo — https://app.tiingo.com/tos/
- **Free Starter plan.**
  - "COMPANY PROVIDES A FREE STARTER PLAN SO THAT YOU CAN EVALUATE THE SERVICES".
  - "you may not write, save, archive, back up, or otherwise retain Tiingo Data in any persistent or durable storage".
  - "A Starter Plan or Trial Plan does not permit persistent storage of Derived Products".
  - Result: public derived output is RESTRICTED on the free plan.
- **Paid Plan.** Derived Products may be distributed "only if [...] (i) it is not, and cannot reasonably be used as, a substitute for access to [...] any Tiingo Data [...] and (ii) it cannot reasonably be reverse engineered". The examples include "rankings, scores, trading signals, classifications". This is conditional, and "does not create a safe harbor".
- **Public raw: RESTRICTED.** Prohibited products include "dashboards, charts [...] that display, deliver, or permit extraction of Tiingo Data".
- The fetched text was cut at 40k characters. The re-read of the full terms is in run 39566940801.

### Alpaca
- **Public raw and Telegram: RESTRICTED.** "Unfortunately, you cannot redistribute Alpaca API data." (https://alpaca.markets/support/redistribute-alpaca-api)
- **Free plan.** "for equities only the IEX exchange, for options only the indicative feed". Standard plans are "real time IEX or 15 mins delayed SIP". This is never execution-grade.
- The Market Data Agreement PDF returned 403, so internal-use rights are UNKNOWN.

### Massive (Polygon), Nasdaq Data Link, Tradier: UNKNOWN
- **Massive:** only the landing page was fetched. "Individual Use" means "personal, individual, and non-business use".
- **Nasdaq Data Link:** the page returned an empty JavaScript shell.
- **Tradier:** the terms page returned 404. "Real-time data is available to all Tradier Brokerage account holders"; delayed data is "delayed industry-standard 15 minutes".

## 2. Sources in use and their gates (earlier runs)

| Source | Automated access | Public display | Gate |
|---|---|---|---|
| Yahoo (yfinance/yahooquery) | RESTRICTED: "using any automated means ... without our express, prior permission"; robots `Disallow: /` | RESTRICTED | `YAHOO_AUTOMATED_ACCESS_APPROVED` (closed) |
| Nasdaq.com / api.nasdaq.com | RESTRICTED: "any process, whether automated or manual, to capture data" | RESTRICTED | `NASDAQ_WEB_AUTOMATION_APPROVED` (closed) |
| Cboe delayed quotes | RESTRICTED | UNKNOWN (not displayed; automation is closed) | `CBOE_DELAYED_AUTOMATION_APPROVED` (closed) |
| NasdaqTrader.com | RESTRICTED: "may not be copied, reproduced, transmitted, displayed [...] without the prior written consent of Nasdaq" | RESTRICTED | `NASDAQTRADER_AUTOMATION_APPROVED` (closed) |
| OCC | RESTRICTED (launching "any automated system, including robots, spiders" is prohibited) | RESTRICTED | `OCC_MARKET_DATA_AUTOMATION_APPROVED` (closed) |
| FINRA API | RESTRICTED: "solely using access credentials provided to Developer by FINRA" | RESTRICTED | `FINRA_API_AUTOMATION_APPROVED` (closed) |
| FRED | UNKNOWN (terms time out; the API terms forbid storing or caching) | UNKNOWN | `FRED_AUTOMATION_APPROVED` (closed) |
| BLS | UNKNOWN (403 on every terms page) | UNKNOWN | `BLS_AUTOMATION_APPROVED` (closed) |
| Google News RSS | RESTRICTED (automated access against robots.txt; `Disallow: /`) | RESTRICTED | `GOOGLE_NEWS_AUTOMATION_APPROVED` (closed) |
| PR Newswire (+ GlobeNewswire, Business Wire) | RESTRICTED / UNKNOWN | RESTRICTED | `PRESS_WIRE_RSS_APPROVED` (closed) |
| openFDA | VERIFIED (CC0) | VERIFIED | open |
| U.S. Treasury, CFTC, Federal Reserve Board | VERIFIED (public domain; cite the source) | VERIFIED | open |
| GDELT | VERIFIED: "unlimited and unrestricted use ... of any kind without fee" with citation and link | VERIFIED | open |
| SEC EDGAR | Allowed with a declared User-Agent (fair-access policy) | public records | needs the `SEC_USER_AGENT` secret |
| TradingView widgets | Display only, inside TradingView's embed, never read back | widget only | open (display only) |

## 3. What this means for the site and Telegram
- **Prices.** No configured or candidate free source allows public raw prices, public derived price analytics, or Telegram sharing. The site shows prices only inside TradingView widgets. Telegram messages carry no prices.
- **Public analysis.** GHAZI's own published analysis uses only VERIFIED public sources: openFDA, Treasury, CFTC, the Fed, GDELT, and SEC once access works.
- **Twelve Data.** Once a key is added, its data stays internal research only. Any public output needs a Redistribution Rights Add-On or a written agreement. Persistent storage is limited to the periods in its documentation, and the guard caches in memory only.
- **Tiingo.** A Paid Plan would be the only route in the text to publishing non-substitutable derived scores. It is conditional, and is not pursued because it is a paid service.
