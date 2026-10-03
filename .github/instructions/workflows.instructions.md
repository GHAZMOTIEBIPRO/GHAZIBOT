---
applyTo: ".github/workflows/**/*.yml"
---

# GitHub Actions / Runtime-State Instructions

Before changing a workflow:
1. map its triggers, schedules, workflow_run dependencies, permissions, concurrency group, artifacts, mutable state paths, and branch writes;
2. identify the owning workflow for every state file it mutates;
3. prove an overlap before calling it a race.

Rules:
- `market-orchestrator.yml` owns the core freshness-driven cadence; do not silently duplicate child schedules.
- Keep concurrency deliberate. Do not add groups mechanically; choose groups from actual shared-resource ownership.
- Prefer one writer per mutable runtime state. If multiple writers are unavoidable, define safe reconciliation.
- Preserve freshness rejection and stale-artifact gates.
- Use bounded retries and explicit failure behavior.
- Keep permissions least-privilege.
- Never expose secrets in logs or artifacts.
- Do not commit high-churn runtime state to `main` when the existing architecture uses bot-state/artifacts.
- `workflow_run` chains must check upstream conclusion and relevant freshness.
- Runtime verification after merge is separate from CI success.
