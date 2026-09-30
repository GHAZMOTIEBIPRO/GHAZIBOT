# AI Engineering Contract

This repository is developed with AI coding agents. Treat this file as the engineering contract.

## Mission
Improve GHAZI Stocks & Options Radar without weakening its data-quality guarantees, safety boundaries, reproducibility, or existing workflows.

## Repository map
- `options_radar/`: core analytics, data fabric, signals, options/stock intelligence, outcomes, calibration, and messaging.
- `tests/`: regression and behavioral tests.
- `.github/workflows/`: scheduled/manual jobs for radar, data health, research, alerts, and validation.
- `docs/`: policies and research documentation.
- `main.py`, `app.py`, `bot_server.py`: application/runtime entry points.

## Non-negotiable constraints
1. Never commit secrets, API keys, Telegram tokens, cookies, or credentials.
2. Do not place credentials in source code, JSON, YAML examples, or generated artifacts.
3. Preserve the documented separation between stock direction analysis and options/flow/Greeks unless a change is explicitly justified and tested.
4. Do not claim that free data proves institutional sweep, fills, slippage, real-time open interest, or guaranteed profitability.
5. Treat stale, missing, malformed, or conflicting market data as a data-quality problem; never silently convert it into a valid trading signal.
6. Do not enable automated trade execution.
7. Prefer additive, backwards-compatible changes. Avoid broad refactors when a focused patch is sufficient.
8. Do not rewrite historical outcome records or calibration evidence merely to improve reported metrics.
9. Preserve source provenance and operational status for market-data decisions.
10. Any behavioral change must have tests.

## Agent workflow
Before coding:
- inspect the relevant modules, tests, docs, and workflows;
- identify dependencies and side effects;
- describe the smallest safe change.

While coding:
- create focused commits;
- keep public interfaces stable where practical;
- add or update regression tests;
- run formatting/linting and targeted tests.

Before proposing merge:
- run the full available test suite;
- run `ruff check .` when available;
- verify no secrets or accidental generated files were introduced;
- summarize changed files, test results, and remaining risks.

## Options/Radar quality rules
- Preserve OCC contract identity and reject non-standard/adjusted contracts when the project policy requires it.
- Preserve liquidity/spread and freshness checks.
- Never infer smart-money intent solely from quote proximity, volume, or open interest.
- Keep target/stop path ambiguity handling intact.
- Keep provider fallback and provider-audit information visible.

## PR discipline
Use a dedicated branch for agent work. Do not push speculative changes directly to `main`.
Every meaningful change should be reviewable as a Pull Request with:
- problem statement;
- implementation summary;
- tests run;
- data-quality/safety impact;
- rollback notes when relevant.
