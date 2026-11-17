# Signal validation report — T1 target baseline (2026-11-17)

Status words follow AGENTS.md. This report covers the published "412 evaluated, 8 T1 hits, 1.94 %"
figure on `trading_readiness.json`.

## 1. Reproduction (exact)

Inputs:
- `bot-state:runtime/data/live/omega_target_state.json`: state updated 2026-11-17T23:00Z, 414 signals.
- `options_radar.omega_target_learning.build_target_calibration`, code as on main `b155195`.

The published cohort is `T1:INTRADAY_1D`. Recomputed from the persisted records it matches the stored calibration
and the readiness file exactly:

| Field | Value |
|---|---|
| Matured | 412 |
| T1 hits | 8 |
| Misses | 404 (402 `MATURED_MISS`, 2 `FAILED` = stop first) |
| Ambiguous (same bar) | 0 |
| Still open | 2 (no bars) |
| Hit rate | 1.94 %, Wilson 95 % CI 0.99 %–3.78 % |

The signals behind the cohort:
- 14 sessions, 2026-10-02 → 2026-10-19.
- Tiers: C 397, B 17. Direction: UPSIDE 298, DOWNSIDE 116.

Bars for every matured record came from `yahooquery`:
- interval 5m 384, 1h 24, 1d 4;
- Yahoo automated access is now `SOURCE_TERMS_BLOCKED` (see `docs/PRICE_SOURCE_INVESTIGATION_2026-10-25.md`).

## 2. Defect found: premature maturity (evaluation v1)

**Rule in v1.** `_evaluate_target` declared `MATURED_MISS` when the number of distinct UTC dates in the bars after the
signal reached the horizon's session count. For `INTRADAY_1D` that count is 1.

**Effect.** The signal's own unfinished date satisfied the rule as soon as the first post-signal bars existed. A
matured target is never re-evaluated (`update_target_outcomes` skips `matured`). The observation window for a
one-session T1 was therefore one evaluation cadence, not one session.

Evidence in the persisted records:
- All 402 `MATURED_MISS` rows have `sessions_observed = 1`.
- Only 2 of 412 targets hit their stop. The stop is as far from entry as T1 (see §3), so a full session would show
  far more stop touches.
- 5 of 8 hits came 0.32–0.82 h after the signal. The other 3 came 14.6–17.1 h after evening signals, at the next
  morning's first bars.
- 190 of 414 signals (46 %) were generated outside regular XNYS hours:
  - 145 had their next open on a later date;
  - 45 were pre-market.

  Under v1 these matured after the first bars of the next session.

The same rule also made multi-session horizons mature at the first bar of their last date.

## 3. Other hypotheses checked

| Hypothesis | Finding |
|---|---|
| Target distance too large for the horizon | Contributing, not proven. T1 is a median 5.46 % from entry (p10 3.06 %, p90 10.53 %), and the invalidation sits at the same distance (1:1). A >5 % move inside one session is uncommon for most of the universe. This cannot be measured until bars are lawful (§5). |
| Incorrect entry activation | No activation step exists. Entry is the scan price at signal time, and bars before the signal are excluded. Not a defect; a later study can add an activation rule. |
| Signal expiration | This is the v1 defect above. |
| Intrabar ordering | 0 same-bar target/stop cases. Same-bar remains `AMBIGUOUS` and never counts as a win. |
| Data gaps | 2 signals never received bars. 28 matured on 1h/1d fallback bars. v1 used the next day's daily bar for a same-day target, which v2 no longer does. |
| Regime / strategy weakness | Not testable on this sample. It covers 14 sessions in one month, and the measurement is invalid. No conclusion is drawn. |

## 4. Fix (evaluation v2) — CODED, TESTED

`options_radar/omega_target_learning.py`, `EVALUATION_VERSION = 2`:

**Measurement window.**
- The horizon is XNYS sessions. The first is the session containing the signal, or the next one when the signal is
  outside regular hours (`minute_to_session(direction="next")`).
- Bars at or after the close of the last required session are ignored. A hit on a later day is a miss, not a win.

**When a miss becomes final.** `MATURED_MISS` needs all three of:
- `now ≥ last close + 20 min` (provider delay);
- bars observed on the last required session date;
- no target or stop touched.

  Otherwise the target stays `OPEN` with `coverage` = `NO_BARS_IN_HORIZON` or `LAST_SESSION_MISSING`.

**Session dates.** Taken from New York time. Date-stamped daily bars keep their own date.

**What each target row carries.** `evaluation_version`, `horizon_close` and `coverage`.

**Calibration.**
- Only v2 records feed `cohorts`, `global_matured_t1_sample` and `calibration_ready`.
- v1 records are kept unchanged under `legacy_v1` with `valid_evidence: false`, `defect: PREMATURE_MATURITY` and the
  same statistics, so the historical baseline stays reproducible.
- Every cohort reports `bar_sources` and `unresolved_missing_bars`.

**Readiness and site.**
- The primary T1 fields now read the v2 cohort, which is empty today.
- The old figure is published as `target_t1_legacy_v1` and explained on the readiness page.

Applied to the real state:
- the primary `T1:INTRADAY_1D` sample is 0;
- the probability gate is closed;
- `legacy_v1.T1:INTRADAY_1D` = 412 / 8 / 1.94 %, `bar_sources = {"yahooquery": 412}`.

**Tests** (`tests/test_omega_target_learning.py`, `tests/test_trading_readiness.py`):
- intraday target open until close;
- later same-session hit counts;
- hit after horizon close is a miss;
- after-close signal measured on the next session;
- missing last-session bars never mature;
- daily-bar coverage;
- legacy separation;
- readiness legacy label and malformed legacy counts.

## 5. What is still not measured

- No valid T1 hit rate exists today. The 1.94 % figure is an artifact of v1 measured on Yahoo bars. It is evidence
  of neither strategy weakness nor strategy strength.
- New signals and v2 evaluations need lawful bars on the runner for the Full Omega Radar path. That path's provider
  chain is Tiingo / Finnhub / Yahoo: Yahoo is gated and no Tiingo or Finnhub key is configured. Until a provider is
  configured, the v2 cohort stays empty.
- **A re-measurement of the 414 legacy signals on Alpaca bars is possible only as owner-private research.**
  `output_policy` marks Alpaca `publish_derived` as UNVERIFIED, and `store_private` excludes logs. Its results may go
  only to the owner's private Telegram, never to logs, bot-state or the site. This is a planned next phase, not done.
- **Out-of-sample comparison** of alternative target definitions (ATR-scaled T1, session-range T1, activation-on-break)
  needs the lawful bars above. It also needs a split by session date, not by signal.

## 6. Status

| Item | Status |
|---|---|
| Baseline reproduction | Reproduced exactly from persisted records |
| Evaluation defect fix | CODED, TESTED (full suite 1807 passed, 2 skipped) |
| Runtime effect | Pending merge and the next Full Omega Radar run |
| Empirical validation of any T1 hit rate | Not available; needs lawful bars |
