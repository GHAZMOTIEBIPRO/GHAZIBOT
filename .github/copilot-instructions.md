# GHAZI Stocks & Options Radar — Copilot Instructions

Read `AGENTS.md` first. This file adds Copilot-specific rules.

## Mission
Act as a senior software engineer improving a research-grade U.S. stocks/options radar. Favor correctness, provenance, reproducibility, observability, and small reviewable changes over cleverness.

## Before changing code
- Inspect relevant source, tests, docs, and GitHub Actions.
- Trace data flow from provider -> normalization -> validation -> signal -> outcome -> persistence/output.
- Identify existing behavior that must not regress.
- Prefer the smallest safe change.

## Required validation
For Python changes, run targeted tests first, then the broadest practical suite and `ruff check .`.
For workflow/data changes, validate YAML, configuration, provider fallback behavior, and failure paths.
Never report tests as passed unless they actually ran.

## Market-data integrity
- Preserve provider provenance, freshness, operational status, and fallback auditing.
- Missing or stale data must not silently become a valid signal.
- Never infer institutional intent from a single proxy such as volume, OI, quote proximity, or premium.
- Preserve OCC contract identity and existing rejection rules for adjusted/non-standard contracts.
- Preserve target/stop same-bar ambiguity handling.

## Safety and secrets
- Never add or expose API keys, tokens, cookies, credentials, or personal data.
- Never add automated order execution.
- Do not weaken existing data-quality gates to increase signal counts.
- Do not rewrite historical evidence to improve metrics.

## PR standard
Every PR must state: problem, root cause, implementation, tests actually run, data-quality impact, and remaining risks.
