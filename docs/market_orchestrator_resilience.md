# Market Orchestrator: missed GitHub schedule recovery

## Incident

On 2026-10-14 the latest discoverable **scheduled** `BLACK BOX Omega Market Orchestrator` run was 38487409578 (2026-10-13 23:58 UTC). GitHub had executed other scheduled News Flash runs while expected central market schedules did not appear. The last orchestrator run exited successfully, so this was a **missing-trigger** issue, not an exception in the child dispatcher.

The reason GitHub omitted the expected schedule events cannot be conclusively established from available run logs alone. GitHub scheduled Actions are best-effort and can be delayed or dropped; an externally independent scheduler would be needed for a strict five-minute SLA.

## Remediation

Retain **one** core market dispatcher at `.github/workflows/market-orchestrator.yml`. Trigger it via:
- Its original market-hours cron (UTC);
- Manual workflow_dispatch;
- Successful `workflow_run` completion of the independent `BLACK BOX News Flash 24x7` workflow, only on `main`;
- A one-time bootstrap `push` when the orchestrator workflow itself changes on `main`.

The news-flash workflow does **not** gain elevated Action permissions or dispatch market engines itself. The news-flash workflow runs its existing independent schedule (also best-effort). Its successful completion only wakes the central owner; the central owner alone performs bounded age checks before dispatching children. No child gets its own cron, and the V11 execution-grade quote gate remains unchanged.

For `workflow_run` wakeups, the central workflow logs the last scheduled invocation age and emits a GitHub warning if overdue by 20+ minutes. A fresh completed news flash may restore overdue scans but **cannot** prove all missing minutes were covered.

## Validation levels

1. PR: full pytest, mandatory Ruff and isolated test assertions around the trigger contract.
2. Merge to main: new `push` bootstrap run must appear and pass.
3. Runtime: a subsequent actual `workflow_run`-sourced Market Orchestrator run should be observed following a successful News Flash job. Do not claim fallback runtime verification until that occurs.
4. Reliability: monitor continuous runs across market hours; a green one-shot push or PR is insufficient to prove five-minute SLA.

If the GitHub scheduler itself is unavailable to **all** independent workflows, neither this recovery nor a second GitHub schedule can guarantee immediate operation. For a strict SLA, configure an off-GitHub scheduler (e.g., a hosted cron calling workflow_dispatch with secure authentication) after explicitly approving the external service.
