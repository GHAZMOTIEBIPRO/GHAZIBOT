# Public-data research archive (DuckDB / Parquet pilot, 2026-11-19)

Status words follow AGENTS.md. Code: `options_radar/public_archive.py`, `scripts/build_public_archive.py`,
`.github/workflows/public-archive.yml`, tests in `tests/test_public_archive.py`.

## Why it is needed (measured, not assumed)
The public files on `bot-state` are snapshots: every copy replaces the last. What the latest copy no longer holds
survives only in git history. Measured on 2026-11-19 over the history since 2026-10-01 (7,852 commits):

| series | observations in history | in the latest copy | revised after first publication |
|---|---|---|---|
| Treasury par yields (5 tenors) | 110 (22 curve dates) | 5 | 0 |
| CFTC TFF positions (5 markets × 3 categories) | 75 (5 weeks) | 15 | 0 |
| DOL initial claims (NSA) | 107 weeks | 104 | 1 (week 2026-10-24: 178,986 → 179,009 on 2026-11-02) |
| NY Fed SOFR / EFFR | 59 | 31 | 0 |
| OFR short-term funding | 32 | 3 | 0 |
| GDELT fetch state | 8 sources, 81 state changes | 1 state each | — |

The claims revision is the decisive case: a backtest on the latest copy would use 179,009 for decisions taken
before 2026-11-02, which is look-ahead. The archive keeps both vintages with the time each was collected.

The earlier conclusion that history starts on 2026-11-17 was an artefact of a shallow clone; with
`git fetch --shallow-since=2026-10-01` the full life of these files is available (first copies 2026-10-18).
No workflow rewrites `bot-state` history (no force push or orphan branch targets it), so the history is the
durable store and the archive is a derived, rebuildable index.

## What is archived, and what is not
| dataset | publisher | rights record | storage / public display |
|---|---|---|---|
| treasury_par_yields | U.S. Treasury | `treasury` (public domain) | allowed |
| cftc_tff_positions | CFTC | `cftc` | VERIFIED / VERIFIED |
| dol_initial_claims_nsa | DOL ETA 539 | `dol_eta539` | VERIFIED / VERIFIED |
| nyfed_reference_rates | NY Fed | `nyfed_reference_rates` | VERIFIED / VERIFIED, notice required |
| ofr_stfm | OFR | `ofr_stfm` | VERIFIED / VERIFIED, credit requested |
| wikimedia_pageviews | Wikimedia | `wikimedia_pageviews` (CC0) | VERIFIED / VERIFIED |
| source_health | GHAZI RADAR | own operational log | — |

Never read: Alpaca (owner-private), Yahoo, Nasdaq.com, Cboe, BLS, FRED, and `signal_tracking.json` (its outcomes
come from Yahoo bars, which are gated). A test enforces the source list and the rights records.

**Prediction vs outcome: not available in the public archive.** Stock and contract outcomes need prices; the
public pipeline has no lawful price source and Alpaca data may not be stored publicly. Owner-private evaluation
runs on the runner and stores nothing (`scripts/run_opening_fib_history.py`, delivered 2026-11-19, run 44501619990).

## Model
- A row is written when a key first appears or a reported value changes (a vintage).
- `collected_at` = the copy's `generated_at` (never later than its commit); `stored_at` = commit time;
  `publisher_time` = the publisher's stamp when given (DOL `Last-Modified`, OFR `source_last_update`);
  `state_commit` = the bot-state commit.
- `as_of(t)`: per key, the last vintage collected at or before `t` — what the pipeline knew then.
- A field the new copy leaves empty is carried over, so it is not a revision; "revised keys" counts only a change
  of the main reported value.
- NY Fed notices are stored in the Parquet file metadata and printed with every report.
- `archive_manifest.parquet` records, per dataset, the last copy read, so a state that did not change still counts
  until then. Source-health hours are split at week / month boundaries.

## Reports (DuckDB SQL over the Parquet files)
Weekly and monthly: Treasury 2Y/10Y and the 10Y–2Y / 10Y–3M spreads with the 10Y change; DOL claims against the
same weeks a year earlier (364 days, not seasonally adjusted); SOFR average and SOFR–EFFR where both exist; CFTC
net positions and their change; OFR latest values; share of hours each news source was failing.

First result: GDELT failed in 100 % of observed hours in every week from 2026-10-12 to 2026-11-19 (HTTP 429, then
the cooldown), which confirms the shared-runner rate limit is persistent, not occasional.

## Measurements (local, 2026-11-19)
| | value |
|---|---|
| file versions read | 789 (4.67 MB JSON) |
| rows written | 511 |
| Parquet size (7 files, zstd) | 21.6 KB |
| read + normalise / write / report | 0.81 s / 0.60 s / 0.15 s |
| new dependency | `duckdb==1.5.6` (MIT, no dependencies; 24 MB wheel), only in `requirements-archive.txt` |

`requirements.txt` is unchanged (18 runtime packages); the security audit now also scans `requirements-archive.txt`.

## Running it
- Weekly (Sunday 07:41 UTC) and on demand: `public-archive.yml` — read-only, no secrets, no push; the summary is
  on the job page and the Parquet files plus `archive_report.json` are a 90-day artifact.
- Locally: `python -m scripts.build_public_archive --repo . --ref origin/bot-state --out /tmp/archive`
  (after `git fetch --shallow-since=2026-10-01 origin bot-state`).

## Limits and next steps
- History before a file's first copy is not available; extending a series further back needs a backfill from the
  publisher (Treasury and CFTC publish full history), labelled with its own collection time.
- The weekly fetch grows with history; once the archive is kept between runs, builds can be incremental.
- Keeping Parquet beyond 90 days (release assets or a `bot-state` path) needs a single writer with
  `contents: write`; it is not done in the pilot and is proposed for owner review.
