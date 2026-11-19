# Open-source project review (2026-11-17)

> **2026-11-19 update.** The review continues in `INTEGRATION_GAP_ANALYSIS.md` (inventory, gaps, ten opportunities,
> roadmap) and `INTEGRATION_VALIDATION.md` (what was run). The 63 recorded decisions are in
> `data/integration_candidates_2026-11-19.json`.
>
> Corrections to this page, found by checking the repository itself:
> - edgartools already has an adapter (`options_radar/edgartools_research_adapter.py`).
> - ruptures (`macro_regimes.py`), arch (SPA test) and alpaca-py (stream gateway) are already used.
>
> Two pilots were added: a workflow and dependency security gate, and an indicator differential test that found and
> fixed a Wilder-seeding defect.

This document continues `OSS_SELECTION_2026-10-29.md`, `OSS_REEVALUATION_2026-10-20.md` and
`OPEN_SOURCE_AND_DATA_SOURCE_DECISIONS.md`. Their standing decisions still hold:
- pandera in use;
- pandas-ta-classic as the indicator reference;
- TA-Lib not added (C build);
- backtesting.py not integrated (AGPL);
- Playwright in use.

No project code was downloaded or executed for this review.

## Method (reproducible)

**Collection.** `python scripts/oss_review.py fetch --output docs/data/oss_candidates_2026-11-17.json`.
- 30 GitHub repository-search queries over the 20 requested categories, sorted by stars, at most 30 results each.
- The 18 named projects are resolved one by one by exact name (18 more searches). Forks are included, so zipline-reloaded and
  alphalens-reloaded are found.
- Renamed repositories are recorded with `resolved_from`.
- Snapshot: 572 repositories, metadata only (licence SPDX id, last push, stars, language, archived, fork).

**Scoring.** `python scripts/oss_review.py score --snapshot docs/data/oss_candidates_2026-11-17.json`. The formula is fixed
and covered by `tests/test_oss_review.py`:

| Part | Points |
|---|---|
| Licence | MIT / BSD / Apache / ISC 3 · MPL / LGPL / EPL 1 · GPL / AGPL / NOASSERTION / none 0 |
| Maintenance (last push) | ≤90 d 3 · ≤365 d 2 · ≤730 d 1 · older or archived 0 |
| Adoption (stars) | ≥10k 3 · ≥1k 2 · ≥200 1 |
| Stack fit | Python 2 · TypeScript / JavaScript 1 |
| Total | 0–11 |

- Core code is allowed only with a licence score of 3 and no standing decision against it (AGPL / GPL / unclear
  licence = concept only, AGENTS.md).

**Relevance screen.** Rule-based, with reasons in `SCREEN`. It excludes:
- crypto venues;
- China A-share tools;
- FX / MetaTrader;
- tools that read sources whose terms block automated access (Yahoo, Finviz, TradingView screener, Stooq,
  Nasdaq.com);
- circumvention tools.

The score measures licence risk, upkeep and stack fit. It does **not** measure correctness. Correctness is only
judged in the deep review below, and only for what was actually read.

## Counts

| Stage | Count |
|---|---|
| Discovered (snapshot) | 572 |
| Metadata-scored | 572 |
| Kept after relevance screen | 452 (excluded: crypto 75, China A-share 23, gated sources 10, FX 10, circumvention 2) |
| Deep-reviewed (named list + selected high scorers) | 27 |
| Newly integrated in this phase | **0** |

## Top 30 after the screen (generated)

| # | Repository | Categories | Licence | Push age (d) | Stars | Lang | L/M/A/S | Total | Core code allowed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | ai_research_agents | Apache-2.0 | 0 | 122966 | Python | 3/3/3/2 | 11 | yes |
| 2 | [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | backtesting | MIT | 0 | 38444 | Python | 3/3/3/2 | 11 | yes |
| 3 | [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | market_data, technical_analysis, signal_validation, backtesting | Apache-2.0 | 1 | 13827 | Python | 3/3/3/2 | 11 | yes |
| 4 | [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | ai_research_agents | Apache-2.0 | 24 | 8445 | Python | 3/3/2/2 | 10 | yes |
| 5 | [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) | backtesting | MIT | 28 | 8410 | Python | 3/3/2/2 | 10 | yes |
| 6 | [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) | named | Apache-2.0 | 15 | 7885 | Python | 3/3/2/2 | 10 | yes |
| 7 | [JerBouma/FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | market_data, technical_analysis | MIT | 0 | 5533 | Python | 3/3/2/2 | 10 | yes |
| 8 | [dgunning/edgartools](https://github.com/dgunning/edgartools) | institutional_13f, sec_filings | MIT | 0 | 2859 | Python | 3/3/2/2 | 10 | yes |
| 9 | [skfolio/skfolio](https://github.com/skfolio/skfolio) | signal_validation, backtesting, risk_sizing | BSD-3-Clause | 0 | 2651 | Python | 3/3/2/2 | 10 | yes |
| 10 | [coding-kitties/investing-algorithm-framework](https://github.com/coding-kitties/investing-algorithm-framework) | backtesting | Apache-2.0 | 0 | 2250 | Python | 3/3/2/2 | 10 | yes |
| 11 | [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | named | Apache-2.0 | 15 | 2018 | Python | 3/3/2/2 | 10 | yes |
| 12 | [pAulseperformance/awesome-pinescript](https://github.com/pAulseperformance/awesome-pinescript) | pine_script | MIT | 0 | 1977 | Python | 3/3/2/2 | 10 | yes |
| 13 | [ScottfreeLLC/AlphaPy](https://github.com/ScottfreeLLC/AlphaPy) | backtesting | Apache-2.0 | 43 | 1788 | Python | 3/3/2/2 | 10 | yes |
| 14 | [alpacahq/alpaca-py](https://github.com/alpacahq/alpaca-py) | market_data | Apache-2.0 | 0 | 1596 | Python | 3/3/2/2 | 10 | yes |
| 15 | [kyky2347/ALTA](https://github.com/kyky2347/ALTA) | ai_research_agents | Apache-2.0 | 12 | 1078 | Python | 3/3/2/2 | 10 | yes |
| 16 | [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | named | Apache-2.0 | 0 | 22572 | C# | 3/3/3/0 | 9 | yes |
| 17 | [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | backtesting | MIT | 4 | 21866 | Jupyter Notebook | 3/3/3/0 | 9 | yes |
| 18 | [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | technical_analysis, ai_research_agents | MIT | 23 | 21586 | Jupyter Notebook | 3/3/3/0 | 9 | yes |
| 19 | [questdb/questdb](https://github.com/questdb/questdb) | market_data | Apache-2.0 | 0 | 17540 | Java | 3/3/3/0 | 9 | yes |
| 20 | [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | named | MIT | 14 | 17114 | Jupyter Notebook | 3/3/3/0 | 9 | yes |
| 21 | [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) | technical_analysis | BSD-2-Clause | 6 | 12418 | Cython | 3/3/3/0 | 9 | no |
| 22 | [zvtvz/zvt](https://github.com/zvtvz/zvt) | technical_analysis, backtesting | MIT | 139 | 4336 | Python | 3/2/2/2 | 9 | yes |
| 23 | [gloom-sh/gloomberb](https://github.com/gloom-sh/gloomberb) | market_data | MIT | 0 | 2770 | TypeScript | 3/3/2/1 | 9 | yes |
| 24 | [ErTasselli/OpenTerminal](https://github.com/ErTasselli/OpenTerminal) | dashboards | MIT | 42 | 2439 | TypeScript | 3/3/2/1 | 9 | yes |
| 25 | [sec-edgar/sec-edgar](https://github.com/sec-edgar/sec-edgar) | sec_filings | Apache-2.0 | 343 | 1423 | Python | 3/2/2/2 | 9 | yes |
| 26 | [TreborNamor/TradingView-Machine-Learning-GUI](https://github.com/TreborNamor/TradingView-Machine-Learning-GUI) | market_data | MIT | 91 | 1026 | Python | 3/2/2/2 | 9 | yes |
| 27 | [stefan-jansen/alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded) | named | Apache-2.0 | 22 | 689 | Python | 3/3/1/2 | 9 | yes |
| 28 | [ryanfrigo/kalshi-ai-trading-bot](https://github.com/ryanfrigo/kalshi-ai-trading-bot) | risk_sizing | MIT | 8 | 660 | Python | 3/3/1/2 | 9 | yes |
| 29 | [Miasyster/QuantGPT](https://github.com/Miasyster/QuantGPT) | signal_validation | MIT | 16 | 514 | Python | 3/3/1/2 | 9 | yes |
| 30 | [BichengWang/RL-pricing](https://github.com/BichengWang/RL-pricing) | ai_research_agents | MIT | 0 | 341 | Python | 3/3/1/2 | 9 | yes |

The automated list still contains noise: general-purpose agents, prediction-market bots and screen-scraper GUIs.
That is why only the deep review below leads to decisions.

## Deep review — named projects and selected high scorers

What was read for each project: the GitHub metadata in the snapshot (licence, push date, stars, fork status) and
the project's own one-line description. "Fit" compares the project with what already exists in this repository.

| Project | Licence (detected) | Last push | Purpose (own description) | Overlap / fit with GHAZI RADAR | Decision |
|---|---|---|---|---|---|
| openbq-org/OpenBB (redirect from OpenBB-finance/OpenBB) | NOASSERTION on GitHub; page states Apache-2.0 | 2026-11-15 | "Open Data Platform for analysts, quants and AI agents." | A wrapper over providers already in the rights matrix (`DATA_SOURCES_BY_CATEGORY_2026-10-26.md` §2); no new lawful source | Not integrated |
| polakowo/vectorbt | NOASSERTION | 2026-11-11 | Research engine for many trading ideas | Fast vectorised backtests. The licence must be read before any use; the bottleneck is lawful data, not speed | Concept only until the licence is read |
| QuantConnect/Lean | Apache-2.0 | 2026-11-17 | Algorithmic trading engine (C#, Python) | Full platform plus brokerage layer; duplicates the walk-forward and outcome audits; C# stack | Not integrated |
| nautechsystems/nautilus_trader | LGPL-3.0 | 2026-11-17 | Rust event-driven trading engine | Execution-grade engine; the project forbids order submission | Not integrated |
| ranaroussi/quantstats | Apache-2.0 | 2026-11-02 | Portfolio analytics | Already used in the shadow report (`docs/quantstats_stock_signals_shadow.md`) | Keep as is |
| lballabio/QuantLib | NOASSERTION (licence text not read) | 2026-11-17 | C++ pricing library | Option pricing needs licensed chains first (Engine F) | Defer |
| TA-Lib/ta-lib-python | BSD-2-Clause | 2026-11-11 | Wrapper for TA-Lib | Standing decision: not added (C build); pandas-ta-classic is the reference | Not added |
| dgunning/edgartools | MIT | 2026-11-17 | SEC EDGAR 10-K, 8-K, XBRL, Form 3/4/5, 13F | Best fit for Engine E. Same SEC hosts and identity rules: it cannot fix the current 403 | **Candidate** after `SEC_USER_AGENT` is set |
| TauricResearch/TradingAgents | Apache-2.0 | 2026-11-17 | Multi-agent LLM trading framework | Analysis here is computed in code with fixed Arabic templates and no model call (CLAUDE.md) | Not integrated (P5 research only) |
| AI4Finance-Foundation/FinRL | MIT | 2026-11-03 | Reinforcement-learning trading | No validated outcomes to learn from yet (§ `signal-validation-report.md`) | Not integrated |
| kernc/backtesting.py | AGPL-3.0 | 2026-08-05 | Backtesting | Standing decision: AGPL, not integrated | Not integrated |
| stefan-jansen/zipline-reloaded | Apache-2.0 (fork) | 2026-11-02 | Algorithmic trading library | Needs bundle ingestion of licensed bars; overlaps the walk-forward | Not integrated |
| dcajasn/Riskfolio-Lib | BSD-3-Clause | 2026-11-04 | Portfolio optimisation | Position sizing research needs validated returns first | Defer |
| PyPortfolio/PyPortfolioOpt (redirect) | MIT | 2026-07-07 | Efficient frontier, Black-Litterman, HRP | Same as above | Defer |
| stefan-jansen/alphalens-reloaded | Apache-2.0 (fork) | 2026-10-26 | Alpha-factor performance analysis | Useful for Engine J (signal quality) once v2 outcomes exist; needs forward returns from lawful bars | **Candidate** (research) |
| FinancePy-Org/FinancePy (redirect) | GPL-3.0 | 2026-11-17 | Derivatives pricing and risk | GPL: concept only | Not integrated |
| vollib/py_vollib | MIT | 2026-05-29 | (no description) Black-Scholes IV and Greeks | Engine F needs licensed, validated chains first | **Candidate** when options data is licensed |
| WallStreetPete/awesome-open-source-trading | CC0-1.0 | 2026-11-11 | Curated map of 450+ projects | Used as a discovery index; its entries overlap the snapshot | Reference only |
| skfolio/skfolio | BSD-3-Clause | ≤90 d | Portfolio optimisation (scikit-learn style) | As Riskfolio | Defer |
| alpacahq/alpaca-py | Apache-2.0 | ≤90 d | Official Alpaca SDK | `bar_providers.py` already calls the same API with explicit feed / timestamp handling | Not needed |
| sec-edgar/sec-edgar, alphanome-ai/sec-parser | Apache-2.0 / MIT | ≤90 d | EDGAR download / parsing | Same SEC identity limits; edgartools covers more forms | Alternatives to edgartools |
| questdb/questdb | Apache-2.0 | ≤90 d | Time-series database | Possible data-lake store, but Java; DuckDB + Parquet fits this Python stack (`data-architecture.md`) | Not chosen |
| JerBouma/FinanceToolkit | MIT | ≤90 d | Financial ratios | Needs fundamentals from FMP (restricted) | Not integrated |
| AI4Finance-Foundation/FinGPT, FinRobot | MIT / Apache-2.0 | ≤90 d | Financial LLMs / agents | Same as TradingAgents | P5 research only |
| convexfi/riskparity.py | MIT | ≤90 d | Risk parity | Same as Riskfolio | Defer |

## What would measurably help, and when

1. **edgartools** (MIT). For Engine E: 13F and Form 3/4/5 parsing, plus filing events.
   - Precondition: the owner sets `SEC_USER_AGENT`.
   - Proof of improvement: filings parsed per day, provenance kept (accession number, filed time).
2. **alphalens-reloaded** (Apache-2.0). For Engine J: information coefficient and quantile returns of signal scores.
   - Precondition: matured v2 outcomes from lawful bars.
3. **py_vollib** (MIT). For Engine F: IV and Greeks with stated model assumptions.
   - Precondition: a licensed, validated option chain (the V11 gate is unchanged).

None of these is added now. Each would add a dependency without any lawful data it can work on today.
