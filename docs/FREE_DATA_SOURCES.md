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

### Alpaca indicative options feed

- Requires Alpaca API credentials.
- Free indicative quotes are modified derivatives of OPRA and trades are delayed.
- It is useful for comparison but is not treated as official OPRA confirmation.

### Tradier developer and brokerage access

- Requires a Tradier account and token.
- Availability, market-data entitlements, latency, and production access depend on the account.

## Public pages not scraped

Barchart, Market Chameleon, Unusual Whales, Cboe, and social-network pages may be useful for manual discovery, but the radar does not scrape them unless an official API or explicit permitted export is available. Social mentions remain supporting context only.

## Evidence policy

- A different website name does not automatically mean an independent evidence class.
- OCC aggregate volume is `market_context`, not `options_quote` or `options_flow`.
- Yahoo/YFinance remains fallback-only and cannot create Tier A.
- Tier A options require a licensed/primary quote and independent flow evidence.
