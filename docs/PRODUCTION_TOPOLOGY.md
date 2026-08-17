# BLACK BOX Ω — Production Topology

_Last reviewed: 2026-08-18_

This file is the canonical map of the repository. If README wording or a historical workflow name conflicts with this document, verify the current workflow triggers and update this document before changing production behavior.

## Non-negotiable architecture rules

1. **Stocks and options are independent decision paths.** Neither may require the other to emit an alert.
2. **Cross-confirmation is context only.** It may enrich/edit an existing Telegram opportunity message but must never create eligibility for either path.
3. **Free Autonomy is the default operating mode.** Paid market-data feeds are not required and may not be silently enabled.
4. **Indicative/delayed/unofficial options data is research-grade only.** It cannot masquerade as production OPRA/execution-quality evidence.
5. **Learning is fail-closed.** Research models have no live authority until explicit out-of-sample gates are satisfied and separately promoted.
6. **`main` is the code branch.** Machine-managed durable research/runtime state belongs in `bot-state`.

## Canonical live paths

### 1) Fast stock discovery

Workflow: `.github/workflows/fast-explosion-radar.yml`

Purpose:
- high-frequency stock discovery;
- earlyness/anomaly/acceleration screening;
- produces candidates for deeper stock validation.

It is **not** the final options engine and does not depend on options data.

### 2) Independent stock radar + Telegram delivery

Workflow: `.github/workflows/stock-radar.yml`

Purpose:
- deep stock validation;
- official-first cause enrichment;
- stock-only alert eligibility;
- direct Telegram delivery after validation;
- durable stock state continuity.

Stock alert decisions remain independent of the options path.

### 3) Independent options contract radar + Telegram delivery

Workflow: `.github/workflows/options-contract-radar.yml`

Purpose:
- strict CALL/PUT contract selection;
- liquidity/spread/Delta/DTE/Vol-OI/flow/Gamma-context/RR guards;
- provider-readiness enforcement;
- direct Telegram delivery after validation;
- guarded outcomes/calibration state.

Options alerts remain independent of the stock alert path. Free/indicative data may be retained for research but may not be relabeled as production OPRA.

### 4) Classical underlying-only direction radar

Workflow: `.github/workflows/classical-direction-radar.yml`

Purpose:
- classical price/volume CALL/PUT direction from the underlying stock;
- separate from the options-chain contract engine;
- requires its own timeframe agreement and data coverage.

It does not substitute for production-grade option-chain evidence.

### 5) Cross-confirmation

Workflow: `.github/workflows/cross-confirmation.yml`

Purpose:
- observe independently-produced stock/options evidence;
- enrich an existing opportunity message when both paths agree;
- never block, suppress, or originate a stock/options decision.

## Telegram transport

Primary delivery occurs inside the stock/options radar jobs after validation. The dedicated files below are **manual/migration fallback paths**, not a second automatic delivery chain:

- `.github/workflows/stock-telegram-alerts.yml`
- `.github/workflows/options-telegram-alerts.yml`

Other Telegram infrastructure:

- `.github/workflows/telegram-connection-keeper.yml` — validates/preserves the Telegram connection state.
- `.github/workflows/radar-health.yml` — transition/recovery health alerts during the relevant market session.
- `.github/workflows/telegram-alerts.yml` — historical/legacy compatibility; do not make it a competing automatic sender.

Policy: one opportunity should map to one Telegram message ID; later confirmation should edit that message instead of creating message spam.

## Research, evidence, and learning

### Stock evidence

- `.github/workflows/adaptive-review.yml` — shadow adaptive evidence review.
- `.github/workflows/stock-state-vault.yml` — durable stock evidence/state persistence.
- `.github/workflows/stock-outcome-auditor.yml` — bias-aware historical 5-minute outcome backfill.
- `.github/workflows/stock-walk-forward.yml` — expanding-session temporal OOS research.
- `.github/workflows/explosion-replay-lab.yml` — separate replay research; not a substitute for actual signal-event walk-forward validation.

Current promotion order is conceptually:

`sample ready -> outcome coverage ready -> independent sessions ready -> temporal walk-forward/OOS -> explicit promotion review`

No intermediate state grants automatic live weight authority.

### Options evidence

- `.github/workflows/options-research-enrichment.yml` — research enrichment.
- `.github/workflows/options-performance-auditor.yml` — Ask-to-Bid performance auditing where executable-quality evidence exists.
- `.github/workflows/options-state-vault.yml` — durable options learning/performance continuity.
- `.github/workflows/expiry-benchmark.yml` — expiry research/benchmarking.

Options calibration must remain inactive until its configured eligible-sample requirements are met. Shadow/indicative samples may be observed but do not become production training samples merely by accumulating quantity.

## Dashboard / research publisher

Workflow: `.github/workflows/options-radar.yml`

Historical name: `GHAZI Stocks and Options Radar`.

Current role:
- research/dashboard generation;
- SEC/FDA/source intelligence;
- public dataset/health export;
- calibration/research continuity;
- **not** the canonical live Stock Radar or Options Contract Radar.

Runtime state is restored/persisted under `bot-state/runtime/`. The dashboard loads the durable runtime dataset first and retains legacy/static fallbacks. Routine market-data refreshes must not push data commits to `main`.

## State ownership

### `main`

Owns:
- application code;
- workflows;
- tests;
- documentation;
- static fallback files retained for migration/backward compatibility.

Routine scanner executions must not use `main` as a mutable database.

### `bot-state`

Machine-managed durable state. Major namespaces:

- `state/stocks/` — stock outcomes, archive, adaptive evidence, audit, walk-forward.
- `state/options/` — options signal/outcome/calibration continuity.
- `state/performance/` — performance report dedupe/continuity where applicable.
- `runtime/` — dashboard/research runtime files formerly committed to `main` every scan.

No secrets/tokens/API credentials are permitted in `bot-state`; vault workflows must reject secret-like keys before persistence.

### GitHub Actions artifacts

Artifacts are short/medium-term handoff and backup, not the sole long-term memory. Housekeeping may prune old artifacts while durable state remains in `bot-state`.

## Health semantics

Health schema v2 uses explicit fields:

- `critical_pipeline_ok=true` means zero critical stock/options/catalyst/export pipeline errors.
- `critical_pipeline_error_count` is the integer count.
- `critical_pipeline_errors` is a deprecated compatibility alias and must not be used in new UI/automation logic.

Provider readiness is separate from workflow success: a workflow can execute successfully while options evidence remains `FALLBACK_ONLY`/research-grade.

## Maintenance / infrastructure

- `.github/workflows/actions-housekeeping.yml` — bounded artifact cleanup.
- `.github/workflows/test.yml` — primary CI regression gate.
- `.github/workflows/structural-explosion.yml` — structural/microfloat research side path; do not merge it into strict options eligibility without an explicit design review.

## Production change checklist

Before merging any change that touches a live path, verify:

1. Stock/options independence is unchanged.
2. Market-session/stale-data gates remain fail-closed.
3. Telegram dedupe/message-ID continuity is preserved.
4. Free Autonomy does not silently enable paid feeds.
5. Research/learning code cannot bypass hard blockers or live promotion gates.
6. Runtime state cannot introduce secrets into the public repository or `bot-state`.
7. CI covers the real CLI entrypoint, not compile-only behavior.
8. Production verification is performed after merge for runtime-boundary/workflow changes.
