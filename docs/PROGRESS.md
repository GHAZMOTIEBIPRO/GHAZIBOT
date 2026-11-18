# Progress — mission "global discovery and data intelligence" (started 2026-11-17)

Status words follow AGENTS.md.

- **PR #440 (evaluation v2 for T1/T2/T3) — MERGED (201ff53).**
  - Reproduced the 412 / 8 / 1.94 % baseline exactly.
  - Found the premature-maturity defect.
  - Kept the legacy records as invalid evidence.
  - See `signal-validation-report.md`.
  - RUNTIME VERIFIED 2026-11-18 (run 44300198117, calibration commit 6bfd94f): evaluation_version 2,
    primary sample 0, legacy 412 / 8 / 1.94 % kept as invalid evidence.
- **PR #442 (Arabic Telegram messages) — MERGED (075d8b2).**
  - Added `telegram_ar.py` (RTL-safe lines, New York and Riyadh times, allowed HTML only).
  - Rewrote the Fibonacci, shadow, catalyst, FDA and ops messages with it.
- **PR #443 (site summary cards and Arabic captions) — MERGED (d74a796).**
  - Production smoke: all pages 200, 0 errors, no overflow.
- **PRs #444–#446 (investor attention, Wikipedia pageviews, CC0) — MERGED.**
  - #444 added the module, builder, workflow and home card.
  - #445 fixed the AQS path: it was missing the `{access}` segment, so 30/33 requests returned 404.
  - #446 sent a Wikimedia-policy User-Agent, `Name/version (https contact) library`.
    - Before: every 11th request got 429 (TSLA, NFLX, PFE), including the retry.
    - Lesson: a client that does not identify itself is put in the most restricted tier, keyed on
      the shared runner IP.
  - RUNTIME VERIFIED on bot-state b0001a8 (2026-11-18 21:52Z): 33/33 OK, 0 errors, data through 2026-11-17.
- **PR #447 (site smoke):** records the labels of the home cards and the `radar.js?v=` it served,
  so a new card on the production domains is checked on the runner.
- **Research documents and the reproducible OSS scoring tool:**
  - documents: `data-source-registry.md` (60 sources), `provider-license-matrix.md`,
    `open-source-project-review.md` (572 scored, 452 kept, 27 deep-reviewed, 0 integrated), `data-architecture.md`,
    `quant-research-roadmap.md`;
  - tool: `scripts/oss_review.py` with `tests/test_oss_review.py`.
- **Next:**
  - owner-private Alpaca re-measurement of the 414 legacy signals (Telegram only);
  - public macro archive (Parquet release assets);
  - SEC archive once `SEC_USER_AGENT` is set.

# Previous mission — "restore leader / index price analysis" (started 2026-10-29)

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
