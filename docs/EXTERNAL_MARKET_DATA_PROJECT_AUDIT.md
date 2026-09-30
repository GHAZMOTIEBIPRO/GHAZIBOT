# External market-data project audit

## Purpose

This document records which capabilities from open-source market-data projects are useful to GHAZIBOT and which are already covered internally.

## Source reviewed

- `simonlin1212/global-stock-data` — Apache-2.0.
- It exposes 13 data layers / 30+ endpoints and emphasizes official-source-first collection.
- Source: https://github.com/simonlin1212/global-stock-data

## Integration decision

| Capability | External project | GHAZIBOT status | Decision |
|---|---|---|---|
| Treasury yield curve | global-stock-data | Already present | Reuse existing GHAZIBOT implementation |
| SEC filings/XBRL | global-stock-data | Already present | Reuse existing SEC modules |
| SEC full-text search | global-stock-data | Already present | Reuse existing EFTS modules |
| FINRA Reg SHO | global-stock-data | Already present | Reuse existing FINRA layer |
| CFTC COT | global-stock-data | Missing as live macro context | **Integrated** |
| CBOE Greeks/0DTE | global-stock-data | Not an approved free production feed | Do not enable automatically; requires source authorization/terms review |
| Yahoo options | global-stock-data | Already present as fallback | Keep behind existing provenance/quality gates |
| News | global-stock-data | Existing multi-source architecture | Do not replace current network with a single source |
| Technical indicators | global-stock-data | Existing project capabilities | Do not duplicate; preserve current signal-path separation |
| Market-wide screener | global-stock-data | Existing discovery/radar paths | Evaluate later against current full-market engine |
| Options GEX/DEX/flow analytics | options-flow-terminal | Useful algorithm reference | Do not import free-tier flow as institutional proof |
| Unusual options burst detection | unusual-options-scanner | Useful algorithm reference | Use only as an evidence feature when source quality permits |
| Multi-signal outcome tracking | trading-signal-scanner | Overlaps with existing outcome/calibration | Borrow test ideas, not duplicate scoring |

## What was actually added

`options_radar.macro.fetch_cftc_cot()` now retrieves the public CFTC Commitments of Traders dataset without an API key and adds it to the existing `build_macro_context()` payload.

The output preserves: source name, source tier, fetch timestamp, latest report date, row count, raw rows, `context_only=true`, and `directional_signal=false`.

CFTC positioning therefore cannot silently become a CALL/PUT signal.

## Quality rules

1. A failed CFTC request is recorded as a macro-data error; it is not converted into empty valid evidence.
2. CFTC is macro context, not proof of institutional trades in an individual stock.
3. The system does not claim real-time CFTC positioning; the report is periodic.
4. No API keys or secrets are committed.
5. No automated trade execution is introduced.
6. External project code is not blindly copied when the same capability already exists internally.

## Next candidates

1. market-wide EDGAR frames/screener enrichment;
2. additional official SEC daily filing-stream coverage;
3. options analytics algorithms from options-flow-terminal, using only validated contract data already accepted by GHAZIBOT;
4. outcome/backtest ideas from trading-signal-scanner.

## Non-goals

This audit does not treat GitHub stars, project descriptions, or a scanner score as evidence that a strategy is profitable. External projects are engineering/data-source references, not performance guarantees.