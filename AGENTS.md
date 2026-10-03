# BLACK BOX OMEGA — AI Engineering Contract

This repository is developed with coding agents. Treat this file as the repository-wide engineering contract.

## Mission
Improve GHAZI Stocks & Options Radar without weakening data honesty, source provenance, runtime reliability, reproducibility, or research safety.

## Source of truth
- GitHub `origin/main` is authoritative.
- Start every task from the latest main and inspect relevant source, tests, workflows, docs, open PRs, and runtime ownership before editing.
- Never resurrect stale branches, artifacts, state, or historical PR code without comparing it to current main.

## Current architecture
Three intelligence paths must remain logically distinct:
1. **Explosion Stocks** — early WATCH -> pressure/pre-explosion/ignition/confirmed research on U.S. stocks.
2. **Classical Direction** — underlying-first CALL / PUT / WAIT analysis; option data must not bias the underlying direction decision.
3. **Option Explosion** — contract-first research with independent contract scoring.

Important current systems:
- `options_radar/v11_gate.py`: strict option production/execution gate. Do not weaken it to increase alert count.
- `options_radar/data_fabric.py`: multi-provider reconciliation and source-family independence.
- `options_radar/omega_target_learning.py`: independent T1/T2/T3 outcome learning.
- `options_radar/failure_attribution.py`: evidence-gated failure-factor learning.
- `options_radar/similar_cases.py`: matured historical analogue research.
- `scripts/build_explosion_options_universe.py` + `.github/workflows/explosion-options-crosscheck.yml`: same-cycle stock-discovery -> option cross-check; discovery may seed a symbol but must not boost contract score.
- `.github/workflows/market-orchestrator.yml`: central freshness-driven cadence owner for core market workflows.
- durable runtime state uses dedicated ownership; do not introduce competing writers.

## Non-negotiable data rules
1. Never manufacture freshness. A local `now()` is not a provider quote timestamp.
2. Distinguish quote time, last-trade time, snapshot time, generated-at time, and provider time.
3. Last-trade age is not quote age.
4. Delayed / sandbox / indicative / unofficial data may remain useful for RESEARCH, WATCH, or CONTEXT, but must not become execution-grade evidence.
5. Same-origin transports do not count as independent confirmation. Yahoo/yfinance/yahooquery are one Yahoo source family.
6. Do not claim sweep, buyer initiation, dealer positioning, fill quality, or institutional intent without data that actually supports the claim.
7. Open interest is not real-time by default; Vol/OI is context, not proof.
8. Missing, stale, malformed, or conflicting data must fail closed at the authority level that requires fresh evidence.
9. Preserve OCC contract identity and adjusted/non-standard contract rejection policies.
10. Never turn a confidence score into a win probability without mature calibrated evidence.

## Outcome and learning rules
- T1, T2, and T3 are tracked independently.
- Same-bar target/stop ordering is ambiguous unless finer evidence resolves ordering; never auto-count it as a win.
- Numerical probability must remain unavailable until the configured mature-sample gates are met.
- Failure-factor penalties require sufficient sample and measurable excess failure versus baseline; association is not causation.
- Similar cases are descriptive historical evidence, not guaranteed probabilities.

## Execution / research separation
- The project is research, decision support, and alerting only.
- Never add automated broker order submission.
- A production/execution-ready option quote requires structured live/licensed evidence, a valid two-sided quote, an absolute verifiable quote timestamp, and acceptable age.
- String labels such as "live", "OPRA", "brokerage", or "execution-grade" are not sufficient evidence by themselves.
- Stream overlays must preserve explicit execution-grade metadata and source identity.

## Runtime and workflow discipline
- Map every mutable state path to a single writer or a safe merge strategy before changing workflow topology.
- Do not call something a race unless overlapping writers to the same mutable state are demonstrated.
- Central orchestrator cadence must not be duplicated by child schedules without a deliberate reason.
- Use bounded retries, freshness gates, dedupe, and fail-closed behavior.
- Keep runtime state churn off `main`; prefer durable state branches/artifacts where the existing design requires them.
- Telegram WATCH and CONFIRMED semantics must remain distinct; do not send WAIT, duplicates, or stale alerts.

## Open-source policy
Before adding external code:
- inspect README, activity, issues, dependencies, security implications, and license;
- prefer concepts/adapters over copied code when duplication is unnecessary;
- MIT/BSD/Apache may be integrated when compatible and attribution is handled;
- GPL/AGPL code must not enter core without explicit license review;
- NOASSERTION/unclear license means do not copy code.

## Engineering loop
For behavioral changes use:
RESEARCH -> INSPECT -> TRACE -> REPRODUCE -> REGRESSION TEST -> IMPLEMENT -> TARGETED TEST -> REVIEW -> FULL RELEVANT TESTS -> PR -> CI -> FIX ROOT CAUSE -> MERGE WHEN GREEN -> RUNTIME VERIFY.

Do not stop after analysis when implementation is authorized.

## Validation
Use the actual repository CI as the contract. At minimum, when applicable:
- `pytest -q`
- current Critical Ruff gate from `.github/workflows/test.yml`
- `ruff check .` as the repository-wide report
- `python -m compileall -q main.py export_web.py run_live_export.py options_radar scripts`
- CLI smoke commands from the CI workflow
- JavaScript syntax checks
- JSON/Vercel validation
- Omega export/UI validation

Never report a test as passed unless it actually ran.

## Git / PR discipline
- Work on a dedicated branch.
- Keep changes focused and reviewable.
- Do not force-push `main`.
- Do not merge failing CI.
- Every PR must state: problem, root cause, implementation, tests actually run, data-quality impact, runtime status, and remaining risks.

## Status language
Always distinguish:
- CODED
- TESTED
- CI GREEN
- MERGED
- RUNTIME VERIFIED
- EMPIRICALLY VALIDATED

Never use DONE / COMPLETE / 100% when runtime or empirical validation is still pending.
