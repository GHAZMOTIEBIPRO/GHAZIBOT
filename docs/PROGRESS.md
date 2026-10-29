# Progress — mission "restore leader / index price analysis" (started 2026-10-29)

Status words follow AGENTS.md: CODED, TESTED, CI GREEN, MERGED, RUNTIME VERIFIED, EMPIRICALLY VALIDATED.

## Done
- **PR #401 — MERGED and RUNTIME VERIFIED.** It added:
  - 4 project skills and the vendored official skills;
  - OHLCV quality rules;
  - the analysis card;
  - the source log;
  - the platform-state card;
  - the bot acceptance test.
- **Provider keys (settings-check run 40854043567, 2026-10-29 10:00 UTC).**
  - Every provider key is absent and every attestation is `UNSET`.
  - Alpaca is not tested because its attestation is not recorded.
  - Therefore no lawful price bars reach the runner. The leader / SPY / SPX reading is blocked by settings, not by code.
- **Keyless liquidity sources: terms read on the runner** (runs 40854791782, 40855108486, 40855269611, 40855619265).
  - **OFR.** "No copyright may be claimed …", with credit requested, and the API is "for public use".
  - **NY Fed.** Licence to use, copy, distribute, access by automated process and store, under a required notice (reference rates).
  - **DOL.** Public service; robots.txt is empty; ETA 539 fields are taken from the DOL data map, page 41.
  - **Fed Board.** "public domain … cite to the Board". H.15 duplicates the Treasury curve, and H.4.1 is a 121 MB package only, so neither is built.
- **Liquidity monitor — CODED and TESTED.** It covers:
  - DOL ETA 539 claims (not seasonally adjusted, same week a year earlier);
  - NY Fed SOFR/EFFR with the target range and notice;
  - OFR tri-party repo rate and volume, and money market fund repo holdings.

  Also part of this work:
  - The shared fetch layer `options_radar/http_fetch.py` keeps these outcomes apart: refusal, rate limit, not found, server error, network failure, and 304.
  - The live dry run (run 40856203424, 10:16 UTC) read every source with HTTP 200, and the second DOL fetch answered 304 Not Modified.
- **Site.** Market-summary facts show claims and SOFR, with the NY Fed notice. Web-interface guideline fixes were applied.

## Next
- PR → CI → merge → first `liquidity-monitor.yml` run on main → check bot-state and the live sites.
- Coverage table (prices / frames / news / options) and the final production / tested / blocked table.

## External requirements (one request at the end)
- Repository secrets: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.
- Variable: `ALPACA_INTERNAL_DATA_USE_AUTHORIZED`.
- Optional secret: `SEC_USER_AGENT`.
- Optional variable: `TELEGRAM_OWNER_USERNAME`.
