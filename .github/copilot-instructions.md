# BLACK BOX OMEGA — Copilot Repository Instructions

Read `AGENTS.md` before changing code.

## Operating principles
- Start from latest `main`.
- Inspect relevant implementation, tests, workflows, docs, state ownership, and open PRs before editing.
- Prefer the smallest correct change over broad refactors.
- Add regression coverage for behavioral fixes.
- Never weaken strict data-quality or V11 gates merely to create more alerts.
- Never invent missing market data, timestamps, provider entitlement, or certainty.

## Architecture invariants
Preserve the three independent intelligence paths:
- Explosion Stocks
- Classical Stock Direction
- Option Explosion

The stock discovery path may seed option research, but stock evidence must not directly raise contract-scoring evidence.

Respect:
- central market orchestrator;
- bot-state/durable-state ownership;
- same-cycle explosion/options cross-check;
- V11 strict gate;
- target learning;
- failure attribution;
- similar historical cases;
- source-family independence;
- zero-cost data policy;
- research vs execution separation.

## Market-data integrity
- Quote timestamp != last-trade timestamp != generated-at timestamp.
- Never substitute `now()` for provider quote freshness.
- Yahoo, yfinance, and yahooquery belong to the same independent source family.
- Delayed/sandbox/indicative/unofficial inputs may support research context but not execution readiness.
- Production authority requires structured evidence, not trusted-sounding text labels.
- Provider failures must be auditable and isolated where safe.

## Learning integrity
- Do not expose numerical probability before mature calibrated samples meet project gates.
- Preserve T1/T2/T3 independence and same-bar ambiguity.
- Failure-factor learning requires adequate sample and excess-failure evidence.
- Similar-case statistics are descriptive, not guarantees.

## Safety
- No automated order execution.
- No secrets in code, logs, public JSON, PR comments, or artifacts.
- Keep workflow permissions least-privilege.
- Do not copy license-incompatible open-source code.

## Validation and completion
Use `.github/workflows/test.yml` as the CI source of truth.
Never claim completion from code changes alone. A meaningful change is complete only after the applicable progression:
CODED -> TESTED -> CI GREEN -> MERGED -> RUNTIME VERIFIED.
