# Progress — mission "restore leader / index price analysis" (started 2026-10-29)

Status words follow AGENTS.md: CODED, TESTED, CI GREEN, MERGED, RUNTIME VERIFIED, EMPIRICALLY VALIDATED.

## Done
- **PR #401 — MERGED and RUNTIME VERIFIED.** It added:
  - 4 project skills and the vendored official skills;
  - OHLCV quality rules;
  - the analysis card;
  - the source log;
  - the platform-state card;
  - the bot acceptance test on real outputs.
- **Provider-key check (settings-check run 40854043567, 2026-10-29 10:00 UTC).**
  - Every provider key is absent: Alpha Vantage, Tiingo, Twelve Data, Finnhub, Polygon, Tradier, MarketData, Intrinio, FRED, SEC_USER_AGENT, openFDA, Benzinga and FilingPulse.
  - Every use attestation is `UNSET`.
  - Alpaca is not tested because the attestation is not recorded.
  - Therefore no lawful price bars reach the runner. The leader / SPY reading is blocked by settings, not by code.
- **Plugins.** financial-analysis, equity-research and market-researcher are installed at project scope.
  - Source: anthropics/financial-services `6056506`, Apache-2.0.
  - Their MCP data connectors are paid accounts and are not available.

## In progress
- Probe the keyless macro / liquidity sources from the runner: OFR STFM, NY Fed rates/RRP, Fed DDP H.15 and DOL claims.
  - Record their terms, structure and latest date.
  - Then build the ones whose terms allow it.

## Next
- Builders for the sources that pass, storing publish/vintage times; site and bot use.
- web-design-guidelines review of `public/`.
- Coverage table (prices / frames / news / options) and the final production / tested / blocked table.

## External requirements (one request at the end)
- Repository secrets: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.
- Variable: `ALPACA_INTERNAL_DATA_USE_AUTHORIZED`.
- Optional secret: `SEC_USER_AGENT`.
- Optional variable: `TELEGRAM_OWNER_USERNAME`.
