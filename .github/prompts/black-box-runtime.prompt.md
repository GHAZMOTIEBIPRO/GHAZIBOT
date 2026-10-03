# BLACK BOX OMEGA — Runtime Verification

Verify runtime health after a merged change.

Read `AGENTS.md` first.

Check the relevant GitHub Actions runs and distinguish:
- CI success;
- merge success;
- first applicable runtime execution;
- artifact/state freshness;
- provider success/failure audit;
- stale rejection;
- writer ownership/race symptoms;
- Telegram delivery or suppression;
- data-health status.

Do not infer runtime success from CI alone.

Report each component as one of:
- MERGED + RUNTIME VERIFIED
- MERGED + RUNTIME PENDING
- CI GREEN / NOT MERGED
- BLOCKED
- DEGRADED

If runtime is degraded, identify the concrete workflow/job/step and root cause before proposing a fix.
