# BLACK BOX Ω — Efficiency Policy

This repository deliberately separates trading latency from operational overhead.

## Protected market cadences

The following high-value paths must not be slowed merely to save GitHub Actions usage:

- Fast Explosion Radar: 5-minute regular-session cadence remains eligible.
- Options Contract Radar: 15-minute cadence remains eligible.
- Classical Direction Radar: 15-minute cadence remains eligible.

They are signal-production paths. Storage housekeeping must never delete the newest artifacts they need.

## Artifact policy

GitHub Actions artifacts are transport/state snapshots, not the long-term source of truth.

- Keep at least the newest 3 artifacts for every artifact name.
- Never delete artifacts younger than 1 hour.
- Prune duplicate historical copies in bounded batches every 4 hours.
- The pruning job changes no trading scores, thresholds, market data, or Telegram decisions.
- Outcome/calibration state is preserved in the newest state artifact; older duplicate snapshots do not add model information.

## Dashboard/deployment policy

The browser reads the latest dashboard payload from the repository's raw `public/data/latest.json` first. Therefore data-only commits do not require a Vercel rebuild. The existing Vercel ignored-build step is expected to skip those commits.

## Data-quality policy

Operational efficiency must never promote weak data:

- Delayed/indicative/unofficial options remain non-production.
- Yahoo/YFinance fallback cannot become OPRA or production flow by consensus.
- Missing or stale execution data must fail closed.
- Stream transport health is telemetry only and cannot create CALL/PUT signals.

## Honest edge policy

Engineering reliability and predictive edge are different measurements. Replay/OOS results decide whether an edge is proven; infrastructure quality alone cannot justify a profitability claim.
