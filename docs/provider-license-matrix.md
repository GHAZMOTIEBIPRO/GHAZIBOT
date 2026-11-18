# Provider licence matrix (2026-11-17)

**Which rows are enforced.**
- Use-by-use rights for every source the code acts on.
- Rows marked **code** are copied from `options_radar/output_policy.py` (`RIGHTS`), as dumped on 2026-11-17. A change
  there changes runtime behaviour; a change here does not.
- Automated-access gates for the other sources live in `options_radar/source_permissions.py` (`GATES`, `CBOE_BLOCK`,
  `PRODUCT_*`).
- Clause quotes are in `DATA_RIGHTS_MATRIX_2026-10-21.md`. Classes and evidence are in `data-source-registry.md`.

**Uses** (defined in `output_policy.py`):

| Use | Meaning |
|---|---|
| fetch | request automatically |
| compute | analyse internally |
| store_private | runner-temporary only; never bot-state, artifacts or logs |
| publish_raw | show raw values on the public site |
| publish_derived | show computed results on the public site |
| telegram_private | the owner's personal chat |
| telegram_public | a group or channel |

**Values.**

| Value | Meaning |
|---|---|
| ✅ ALLOWED | Permitted |
| 👤 OWNER_AUTHORIZED | Needs the named owner variables set to `true` |
| ❔ UNVERIFIED | Denied until the text is verified |
| ⛔ DENIED | Not permitted |

## Code-enforced (`output_policy.RIGHTS`)

| Source | fetch | compute | store_private | publish_raw | publish_derived | telegram_private | telegram_public | Owner variables |
|---|---|---|---|---|---|---|---|---|
| alpaca_iex (stocks) | 👤 | 👤 | 👤 | ⛔ | ❔ | 👤 | ⛔ | `ALPACA_INTERNAL_DATA_USE_AUTHORIZED`; private alerts also need `ALPACA_PRIVATE_ALERTS_AUTHORIZED` |
| alpaca_indicative_options | 👤 | 👤 | 👤 | ⛔ | ❔ | 👤 | ⛔ | same |
| tradingview_widget | ⛔ | ⛔ | — | ✅ (inside the embed) | — | — | — | — |
| treasury | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| cftc | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| openfda | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| sec_edgar | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | `SEC_USER_AGENT` for access (fair-access identity) |
| clinicaltrials | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | attribution (ODbL) |
| yahoo | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | — |
| nasdaq_web | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | — |

**Consequences.**
- Nothing derived from Alpaca bars may appear on the site, in logs or in a group. That includes hit rates, levels and
  scores. It may reach only the owner's private chat.
- The T1 re-measurement planned in `signal-validation-report.md` §5 is therefore Telegram-private.

## Gated by `source_permissions` (automated access closed)

| Source | Gate (variable stays `false`) | Why (rights matrix) |
|---|---|---|
| Yahoo (yfinance / yahooquery) | `YAHOO_AUTOMATED_ACCESS_APPROVED` | ToS forbids automated means; robots `Disallow: /` |
| Nasdaq.com | `NASDAQ_WEB_AUTOMATION_APPROVED` | "any process … to capture data" |
| NasdaqTrader | `NASDAQTRADER_AUTOMATION_APPROVED` | written consent required |
| Cboe delayed quotes | `CBOE_DELAYED_AUTOMATION_APPROVED` | automated extraction prohibited (do not re-enable) |
| OCC | `OCC_MARKET_DATA_AUTOMATION_APPROVED` | robots / automated systems prohibited |
| FINRA API | `FINRA_API_AUTOMATION_APPROVED` | credentials-bound terms |
| FRED | `FRED_AUTOMATION_APPROVED` | API terms forbid storing |
| BLS | `BLS_AUTOMATION_APPROVED` | terms unreadable from runners (403) |
| Google News RSS | `GOOGLE_NEWS_AUTOMATION_APPROVED` | robots `Disallow: /` |
| Press wires | `PRESS_WIRE_RSS_APPROVED` | terms restrict reuse |

An attestation variable records the owner's statement. It is not the provider's permission (CLAUDE.md), and a
RESTRICTED source needs the provider's written permission.

## Not in code (no key configured) — rights by use

Source text for each row is in the rights matrix or the registry.

| Source | fetch / compute | public raw | public derived | Telegram (any) | Note |
|---|---|---|---|---|---|
| Tiingo (free) | personal evaluation | ⛔ | ⛔ | ⛔ | Paid plan: conditional non-substitutable derived output |
| Finnhub | personal | ⛔ | ⛔ | ⛔ | "derived results" also restricted |
| Twelve Data (free) | internal, non-commercial | ⛔ add-on | ⛔ | ⛔ | — |
| Alpha Vantage | personal | ⛔ | ⛔ | ⛔ | 25 requests/day |
| FMP | personal | ⛔ | ⛔ | ⛔ | display agreement needed |
| EODHD | personal | ⛔ | ⛔ | ⛔ | 20 calls/day |
| MarketData.app | personal | ⛔ | ⛔ | ⛔ | OPRA vendor agreement for options display |
| Tradier | brokerage account holders | ⛔ | ⛔ | ⛔ | no account entitlement asserted |
| Massive | per plan | business product | business product | business product | UTP / CME agreements apply |
| Databento | per dataset | venue licence | venue licence | venue licence | licence fees passed through |
| Cboe DataShop | internal | ⛔ | extra fees and terms | ⛔ | — |
| ThetaData / ORATS | personal / internal | ⛔ | ⛔ | ⛔ | paid |
| SEC 13F / Form 3/4/5 data sets | ✅ | ✅ | ✅ | ✅ | public records; delayed disclosures must be labelled as such |
| BEA / Census / EIA | ✅ with registration | ✅ | ✅ | ✅ | attribution / no-endorsement notices |
| World Bank | ✅ | ✅ (CC BY 4.0) | ✅ | ✅ | attribution |
| Wikimedia pageviews | ✅ | ✅ (CC0) | ✅ | ✅ | User-Agent, rate limits |
| OpenFIGI | ✅ (5 or 20 req/min) | ❔ | ❔ | ❔ | 2018 terms not read in full |

## Rules that follow

1. **SIP label.** A SIP label is kept only when the bar came from the SIP feed. `bar_providers.py` retries IEX once
   when SIP is refused, and labels the result IEX.
2. **No silent mixing.** Never mix families inside one "confirmed" value. Yahoo transports are one family; Alpaca IEX
   and Alpaca SIP are one account, not independent confirmation.
3. **Delayed disclosures.** 13F (≤45 days after quarter end) and Form 4 (2 business days) are shown as filing-time
   facts, never as current positioning (Engine E).
4. **Upgrading a row.** A row moves to ✅ only with the provider's own text, quoted in the rights matrix, and a code
   change in `output_policy.py` with a test.
