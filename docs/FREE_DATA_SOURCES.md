# Free and official data sources

The radar may use free sources only when their access method is documented and permitted.

## Automated without an API key

### OCC Volume Query

- Official source: The Options Clearing Corporation.
- Access: documented CSV batch endpoint at `marketdata.theocc.com/volume-query`.
- Role in the radar: aggregate CALL/PUT volume context for daily, weekly, and monthly profiles.
- Limitations: not a live quote, not OPRA BBO, not transaction-level options flow, and cannot create Tier A.
- Audit output: `data/live/occ_audit.json` and `expiry_radar.occ_official_context` in `public/data/latest.json`.

### SEC EDGAR data APIs

- Official submissions and XBRL Company Facts APIs.
- No API key is required.
- Role: filings, fundamentals, dilution risk, insider and ownership events.

### FINRA Reg SHO daily short-sale volume

- Official market context.
- It is not short interest and cannot determine CALL or PUT direction by itself.

## Free account or credentials required

### MarketData.app historical option quotes

- Requires a free MarketData.app API token.
- Free accounts can query historical option quotes; the project uses this only for closed-session contract-volume history and anomaly research.
- Historical rows are not execution-grade and do not upgrade V11 or live quote freshness.
- The adapter is credit-aware by design because one historical range can return multiple days for one OCC contract.
- Historical Greeks are not assumed; they remain unavailable on historical requests.

### Alpaca indicative options feed

- Requires Alpaca API credentials.
- Free indicative quotes are modified derivatives of OPRA and trades are delayed.
- It is useful for comparison but is not treated as official OPRA confirmation.

### Tradier developer and brokerage access

- Requires a Tradier account and token.
- Availability, market-data entitlements, latency, and production access depend on the account.

## Public pages not scraped

Barchart, Market Chameleon, Unusual Whales, Cboe, and social-network pages may be useful for manual discovery, but the radar does not scrape them unless an official API or explicit permitted export is available. Social mentions remain supporting context only.

### Zero-key self-collected contract volume history

- Yahoo/YFinance or another permitted chain can contribute a daily volume observation only when the row carries an explicit last-trade timestamp.
- The store never substitutes workflow collection time for market time.
- Repeated observations from the same trading date are deduplicated; only the largest provider-reported cumulative volume is retained for that session.
- The history is persisted across GitHub Actions runs and becomes useful for anomaly baselines only after enough distinct prior sessions accumulate.
- This history is research-only and cannot prove a sweep, buy-to-open, dealer positioning, or execution-grade option pricing.

## Enable MarketData.app free historical research

The adapter is already wired into the options radar. It stays inactive until the repository has a token.

1. Create a free MarketData.app account and copy its API token.
2. In the GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Use the exact secret name `MARKETDATA_TOKEN`, then save the token as its value. Do not commit it to the repository or paste it into issues, Telegram, or logs.
4. Run **GHAZI Stocks and Options Radar** from GitHub Actions and inspect that run's logs and result artifact for a successful `marketdata` `option_volume_history` attempt.

This enables historical contract-volume research only. It does not change the live option quote provider, make quotes execution-grade, or promote V11. A Yahoo-only quote chain should continue to show `FALLBACK_ONLY` after the token is added.

## Contract Guardian interpretation

- Telegram acceptance confirms message delivery, not quote quality or trading readiness.
- Untimestamped contract values remain indicative observations. They do not establish P&L, MFE/MAE, target achievement, or a V11 signal.
- Provisional target/stop states remain provisional until the underlying price and its source have verifiable timestamps.
- Premium targets are modeled research ranges, not guaranteed prices.

## Evidence policy

- A different website name does not automatically mean an independent evidence class.
- OCC aggregate volume is `market_context`, not `options_quote` or `options_flow`.
- Yahoo/YFinance remains fallback-only and cannot create Tier A.
- Tier A options require a licensed/primary quote and independent flow evidence.


## Open-source fallback and validation additions

- **Yahooquery (MIT):** alternate transport to Yahoo's unofficial data family. It may improve resilience when yfinance transport fails, but it is explicitly the same `yahoo` evidence family and never increases independent-source quorum.
- **py_vollib / py_vollib_vectorized (MIT):** weekly/manual shadow validation of modeled Black-Scholes Greeks. Validation evidence has no live decision authority.
- **CFTC Traders in Financial Futures:** official weekly macro-positioning context from the CFTC Public Reporting Environment. It is `context_only` and cannot create CALL/PUT direction by itself.

## Free Data Fabric V2

### SEC Form 144

- Electronic Form 144 filings are official SEC supply-context evidence.
- The parser records proposed shares, aggregate market value, reported units outstanding, approximate sale date, seller/issuer relationship, and disclosed sales from the prior three months when present.
- A Form 144 filing is a **notice of a proposed sale**. It is not treated as proof that the sale executed.
- In Microcap Hunter it can add a modest research-only supply-risk penalty, but it is not equivalent to an ATM, registered direct, public offering, or other dilution filing.

### OCC period-aware querying

- Daily Volume Query context uses recent business dates.
- Weekly queries use completed Friday report dates rather than probing every business day.
- Monthly queries use the last business day of completed calendar months rather than partial current-month dates.
- OCC remains aggregate context only and cannot establish sweep direction, buy-to-open activity, dealer positioning, or Tier A execution readiness.

### Source-family health

`public/data/free_data_health.json` now distinguishes official source families from open-source shadow validators.

- SEC submissions and Company Facts share the `sec_edgar` family.
- Two transports from the same evidence family do not increase source quorum.
- An official-source outage cannot be replaced with a shadow GitHub source for decision authority.
- Health checks never grant signal authority; they only report availability and provenance.

