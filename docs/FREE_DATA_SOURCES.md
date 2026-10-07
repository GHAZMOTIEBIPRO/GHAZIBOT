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

## Evidence policy

- A different website name does not automatically mean an independent evidence class.
- OCC aggregate volume is `market_context`, not `options_quote` or `options_flow`.
- Yahoo/YFinance remains fallback-only and cannot create Tier A.
- Tier A options require a licensed/primary quote and independent flow evidence.


## Open-source fallback and validation additions

- **Yahooquery (MIT):** alternate transport to Yahoo's unofficial data family. It may improve resilience when yfinance transport fails, but it is explicitly the same `yahoo` evidence family and never increases independent-source quorum.
- **py_vollib / py_vollib_vectorized (MIT):** weekly/manual shadow validation of modeled Black-Scholes Greeks. Validation evidence has no live decision authority.
- **CFTC Traders in Financial Futures:** official weekly macro-positioning context from the CFTC Public Reporting Environment. It is `context_only` and cannot create CALL/PUT direction by itself.
