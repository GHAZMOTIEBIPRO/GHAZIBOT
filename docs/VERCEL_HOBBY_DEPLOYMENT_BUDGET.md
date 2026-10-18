# GHAZI RADAR — stay within Vercel Hobby daily deployment quota

Verified 2026-10-18: Vercel returned HTTP 402
`api-deployments-free-per-day`, specifically the Hobby 100-deployment
creation limit within 24 hours. The previous site deployment remained
READY while commit 821387c (news precision improvements) was merged but
could not be newly deployed on the public alias.

## Root cause

Two separate existing workflows mirrored every successful research cycle's
changing `health.json` and `data-status.json` to **main**, each commit
triggering a Vercel Git deployment creation, often multiple times an hour.
An ignore-build command cannot prevent Vercel from *creating* a deployment
record for every incoming Git commit.

## Fix and trade-off

Both mirror owners now consult a single pure helper
`scripts/vercel_metadata_budget_guard.py` after reading latest main.
They only create a new main metadata snapshot when the *oldest* incoming
health/status timestamp is at least 90 minutes later than the *newest*
existing static timestamp. Older/out-of-order updates are refused.

- The canonical runtime `bot-state` publisher is **not throttled**.
- Browser runtime components independently consume latest `bot-state`
  JSON with displayed timestamps; option execution gates are unchanged.
- Static `/health` and `/data-status` endpoints can lag the real runtime
  by up to roughly 90 minutes plus scan delay; treat their embedded
  `generated_at` as authoritative, not as a live heartbeat.
- Health publishing is not disabled; first/missing status snapshots still
  publish, with explicit fail-closed timezone checks.
- Additional UI code releases and other distinct Git pushes consume the
  remaining Hobby deployments; this guard reduces one major contributor
  but cannot guarantee staying under 100 when many unrelated pushes occur.

Reference: https://vercel.com/docs/limits
