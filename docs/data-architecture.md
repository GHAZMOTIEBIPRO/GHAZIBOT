# Data architecture (2026-11-17)

This document evaluates the existing infrastructure first and then proposes the smallest changes that give a
reproducible historical store. Nothing here changes a writer or a workflow yet.

## 1. What exists

| Layer | Where | Properties |
|---|---|---|
| Runtime state | `bot-state` branch (JSON, single writer per file, CLAUDE.md) | Durable, versioned by git, **public**: the repository is public |
| Public site data | `public/data` on main (health metadata mirrored twice daily) + `bot-state` read via raw.githubusercontent | Public |
| Workflow artifacts | GitHub Actions artifacts | Retention-limited; downloadable by signed-in users of a public repository |
| Runner temp | `$RUNNER_TEMP` | Deleted after the job; the only place `store_private` may use (`output_policy.py`) |
| Validation | `pandera` (in use), `options_radar/ohlcv_quality.py`, `exchange_calendars` (XNYS) | Row rules, completed vs forming bars, split suspects |
| Fetching | `options_radar/http_fetch.py` | Separates refusal / rate limit / not found / server error / 304; refusals never retried |

**Constraint that decides the design.** The repository, its logs, its artifacts and `bot-state` are all public. So:
- **FREE_PUBLIC data** (SEC, Treasury, CFTC, NY Fed, OFR, DOL, openFDA, ClinicalTrials, GDELT) may be archived in
  the repository's public storage.
- **Licensed or owner-private data** (Alpaca bars, Alpaca indicative options) may **not** be stored anywhere in this
  repository, and not in logs. Today the lawful pattern for them is re-fetch on demand inside a runner, compute,
  then deliver privately to the owner and discard.
- A durable private store for licensed data needs two things:
  - the provider's terms permitting persistent storage (the Alpaca agreement is unread: the PDF returned 403);
  - storage outside this public repository, owned by the owner.

  Both are owner decisions.

## 2. Proposed tiers

| Tier | Content | Format / store | Who may read |
|---|---|---|---|
| `public` | Derived results from FREE_PUBLIC sources; site JSON | JSON on `bot-state` (as today) | Everyone |
| `archive-public` | Historical FREE_PUBLIC observations, with vintage and provenance | Parquet, one dataset per source, partitioned by `year`; published as **GitHub Release assets** (not git history) or an owner bucket | Everyone |
| `research-private` | Results computed from licensed data (hit rates, levels, scorecards) | Never persisted; Telegram-private delivery only | Owner |
| `restricted` | Raw licensed data (bars, quotes, chains) | Runner temp only, deleted with the job | Nobody after the job |

Large history is never committed to git history. The 572-row OSS snapshot (`docs/data/`) is small metadata, not a
dataset.

## 3. Record contract (every archived row)

| Field | Rule |
|---|---|
| `source` + `source_family` | Family groups same-origin transports (AGENTS.md rule 5) |
| `observation_time_utc` | The publisher's own time for the value: bar start, release date, filing accepted time |
| `published_at_utc` / `vintage` | When the publisher made the value available. No look-ahead (CLAUDE.md) |
| `fetched_at_utc` | Our clock; never used as freshness of the value |
| `session` | XNYS session date via `exchange_calendars`, for market data |
| `adjustment` | `raw` / `split` / `all`, for prices; never mixed in one series |
| `feed` | `sip` / `iex` / `indicative`, for market data |
| `provenance` | URL or API path, request parameters, HTTP status, ETag / Last-Modified when present |
| `dedupe_key` | Deterministic hash of (source, entity, observation time, vintage) |

**Incremental updates.**
- Fetch only after the last stored vintage. Use conditional requests (ETag / 304), as the liquidity monitor already
  does.
- Append, then deduplicate on `dedupe_key`; never rewrite a stored vintage.

**Schema validation.** A pandera schema per dataset, run before writing. A failing batch is rejected whole, with its
code (`DATA_ERROR`) and row count.

**Missing data.** Expected publication calendars per source (weekly CFTC, quarterly 13F, XNYS sessions). A missing
expected observation is recorded as `MISSING`, never filled.

**Corporate actions.**
- Prices are kept `raw` with a separate split / dividend table where the source provides one.
- Without that table, a series is labelled `adjustment: unknown`, and `SPLIT_SUSPECT` checks
  (`ohlcv_quality.py`) gate its use.

## 4. Query engine

**DuckDB** reads the Parquet tiers directly, in a runner or locally, for research queries:
- walk-forward splits by session date;
- cohort statistics;
- calibration.

It needs no server and no credentials.

**PostgreSQL** is **not** recommended now:
- operational state is small JSON with one writer per file;
- a database adds a hosted service, credentials and a second source of truth.

Reconsider only if concurrent writers or row-level queries on the site become necessary.

## 5. Increments (each one PR, CI, runtime check)

1. **`archive-public` for SEC 13F and Form 3/4/5 data sets** (quarterly ZIPs, public records).
   - Precondition: `SEC_USER_AGENT`; today SEC answers 403.
   - Output: Parquet in a release, plus a manifest with row counts and hashes.
2. **Macro archive.** Treasury curve, CFTC TFF, DOL claims, NY Fed SOFR / EFFR (with the required notice), OFR,
   with vintages.
   - These sources already work, so this is the first increment that can be runtime-verified without owner action.
3. **DuckDB research helper.** Reads the manifest, verifies hashes, and exposes session-aligned frames to research
   scripts.
4. **Licensed data.** No storage. Private re-fetch jobs deliver results by Telegram only, until the owner provides a
   storage-permitting licence and a private store.
