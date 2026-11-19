"""Build docs/data/integration_candidates_2026-11-19.json: decisions joined to verified metadata.

Decisions are written here, with the evidence level for each; licence, last push, stars and
fork/archive flags come from the GitHub snapshots (`oss_review.py verify` / `fetch --extended`),
never typed by hand. Evidence levels, weakest first:
  metadata   - GitHub/PyPI metadata and the project's own description only
  repo_usage - this repository already declares or imports it (file named)
  read       - the project's source or documentation was read for the stated point
  ran        - it was installed and run here on this repository or on test data
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

STATUSES = ("ALREADY_IN_USE", "PARTIALLY_INTEGRATED", "CONCEPT_ALREADY_IMPLEMENTED", "READY_FOR_PILOT",
            "CONDITIONAL", "RESEARCH_ONLY", "DEFERRED", "BLOCKED", "REJECTED")

# name: (purpose, existing overlap, new capability, data rights, cost, risk, decision, evidence, note)
D: dict[str, tuple[str, str, str, str, str, str, str, str, str]] = {
    # A - data and filings
    "openbq-org/OpenBB": ("unified access to research data providers", "provider access already in bar_providers / http_fetch",
                          "none: a wrapper over providers already in the rights matrix", "per provider", "free code",
                          "large dependency tree; GitHub licence NOASSERTION (PyPI: Apache-2.0)", "REJECTED", "metadata",
                          "no new lawful source; redirect from openbb-finance/OpenBB"),
    "alpacahq/alpaca-py": ("official Alpaca SDK", "options_radar/stream_gateway.py (requirements-stream.txt); bars via bar_providers REST",
                           "none for bars", "owner-private (Alpaca terms)", "free tier", "low", "PARTIALLY_INTEGRATED",
                           "repo_usage", "stream path only"),
    "dgunning/edgartools": ("SEC EDGAR filings, Form 3/4/5, 13F, XBRL", "options_radar/edgartools_research_adapter.py (requirements-research.txt)",
                            "Form 4 / 13F / XBRL parsing once SEC answers", "SEC: public domain; fair-access identity required",
                            "free", "SEC returns 403 until SEC_USER_AGENT is set", "CONDITIONAL", "repo_usage",
                            "adapter exists; blocked only by the owner's SEC_USER_AGENT secret"),
    "alphanome-ai/sec-parser": ("10-K/10-Q section parsing", "edgartools adapter", "semantic sections of filings",
                                "SEC public domain", "free", "same SEC identity limit", "DEFERRED", "metadata",
                                "revisit after SEC access works"),
    "JerBouma/FinanceDatabase": ("symbol classification database", "options_radar/sectors.py, symbol_directory",
                                 "sector/industry for ~300k symbols", "compiled from mixed sources: provenance unverified",
                                 "free", "data provenance", "RESEARCH_ONLY", "metadata", "data rights must be read before use"),
    "JerBouma/FinanceToolkit": ("financial ratios", "options_radar/sec_fundamentals.py", "ratio library",
                                "needs Financial Modeling Prep (restricted)", "paid key for depth", "data rights",
                                "BLOCKED", "metadata", "SEC companyfacts is the lawful fundamentals path"),
    "OpenByteInc/QuantDinger": ("full research/trading platform", "duplicates the whole system", "none",
                                "per provider", "free code", "scope", "REJECTED", "metadata", "architecture reference only"),
    # B - technical analysis
    "xgboosted/pandas-ta-classic": ("indicator library", "indicator reference in tests", "differential oracle for every internal EMA/ATR/RSI/VWAP",
                                    "n/a", "free", "none (dev dependency)", "ALREADY_IN_USE", "ran",
                                    "2026-11-19 differential test found and fixed the RSI/ATR seed defect"),
    "TA-Lib/ta-lib-python": ("TA-Lib wrapper", "pandas-ta-classic uses the same SMA-seeded Wilder convention", "none",
                             "n/a", "free", "C library build on every runner", "REJECTED", "read",
                             "standing decision; pandas-ta-classic rma documents TA-Lib parity"),
    "nardew/talipp": ("incremental indicators", "batch indicators", "streaming updates", "n/a", "free",
                      "last push 435 days ago", "DEFERRED", "metadata", "no streaming need yet"),
    "VladPetrariu/Qullamaggie-breakout-scanner": ("breakout/consolidation scanner", "breakout_pressure.py, vcp_minervini_shadow.py, daily_volume_breakout_shadow.py",
                                                  "none", "depends on its data source", "free", "28 stars", "CONCEPT_ALREADY_IMPLEMENTED",
                                                  "metadata", ""),
    "xang1234/stock-screener": ("CANSLIM / Minervini screens", "vcp_minervini_shadow.py", "none", "depends on its data source",
                                "free", "low", "CONCEPT_ALREADY_IMPLEMENTED", "metadata", ""),
    "pAulseperformance/awesome-pinescript": ("Pine Script index", "none", "reference reading", "n/a", "free", "none",
                                             "RESEARCH_ONLY", "metadata", ""),
    # C - evaluation and statistics
    "stefan-jansen/alphalens-reloaded": ("factor / signal IC and quantile returns", "no IC evaluation in the code (0 files)",
                                         "information coefficient of scores vs forward returns", "needs lawful forward returns",
                                         "free", "no matured v2 outcomes yet", "CONDITIONAL", "repo_usage",
                                         "pilot when opening-fib / v2 outcomes mature"),
    "ranaroussi/quantstats": ("performance reports", "scripts/run_quantstats_stock_shadow.py", "none", "n/a", "free", "low",
                              "ALREADY_IN_USE", "repo_usage", ""),
    "statsmodels/statsmodels": ("statistical tests", "Wilson intervals in omega_target_learning; arch SPA", "regressions, tests",
                                "n/a", "free", "low", "DEFERRED", "metadata", "add when a test needs it"),
    "bashtage/arch": ("volatility models, bootstrap tests", "options_radar/explosion_model_lab.py (SPA)", "GARCH if needed",
                      "n/a", "free", "GitHub NOASSERTION; PyPI: NCSA (permissive)", "ALREADY_IN_USE", "repo_usage", ""),
    "deepcharles/ruptures": ("change-point detection", "options_radar/macro_regimes.py", "none", "n/a", "free", "low",
                             "ALREADY_IN_USE", "repo_usage", ""),
    "skfolio/skfolio": ("portfolio optimisation", "none", "risk models", "n/a", "free", "out of scope (alerts only)",
                        "DEFERRED", "metadata", ""),
    "stefan-jansen/zipline-reloaded": ("backtest engine", "walk-forward + outcome audits", "none", "needs bundles of licensed bars",
                                       "free", "duplicate engine", "REJECTED", "metadata", ""),
    "QuantConnect/Lean": ("event-driven engine (C#)", "walk-forward + outcome audits", "none", "per provider", "free code",
                          "C# stack, duplicate", "REJECTED", "metadata", ""),
    "polakowo/vectorbt": ("vectorised backtests", "walk-forward", "speed", "n/a", "free code",
                          "licence NOASSERTION on GitHub, none on PyPI (Commons Clause per project)", "BLOCKED", "metadata",
                          "LICENSE_REVIEW_REQUIRED"),
    "nautechsystems/nautilus_trader": ("execution-grade trading engine", "none needed", "none", "per provider", "free code",
                                       "LGPL-3.0; execution scope is forbidden here", "REJECTED", "metadata", ""),
    "optuna/optuna": ("parameter optimisation", "none", "tuning", "n/a", "free", "overfitting without a matured sample",
                      "DEFERRED", "metadata", "only with walk-forward and a frozen test set"),
    # D - ML / AI
    "microsoft/qlib": ("quant ML platform", "none", "model zoo", "needs its own data", "free", "heavy; no matured sample",
                       "DEFERRED", "metadata", ""),
    "AI4Finance-Foundation/FinGPT": ("financial LLMs", "fixed Arabic templates, no model call (CLAUDE.md)", "text analysis",
                                     "n/a", "compute", "unverifiable claims", "RESEARCH_ONLY", "metadata", ""),
    "TauricResearch/TradingAgents": ("multi-agent LLM trading", "same", "none allowed in the decision path", "n/a",
                                     "LLM cost", "persuasive text is not evidence", "RESEARCH_ONLY", "metadata", ""),
    "scikit-learn/scikit-learn": ("ML models", "none", "classifiers", "n/a", "free", "no matured sample", "DEFERRED", "metadata", ""),
    "shap/shap": ("model explanations", "none (no production model)", "explanations", "n/a", "free", "nothing to explain yet",
                  "DEFERRED", "metadata", ""),
    "evidentlyai/evidently": ("data / model drift monitoring", "pandera + ohlcv_quality + source_log", "drift reports",
                              "n/a", "free", "heavy", "DEFERRED", "metadata", ""),
    "langchain-ai/langgraph": ("LLM workflow graphs", "none", "none allowed in production", "n/a", "LLM cost", "policy",
                               "REJECTED", "metadata", ""),
    # E - site, charts, storage
    "tradingview/lightweight-charts": ("web charts", "TradingView widget embeds", "charts of our own series",
                                       "only for publishable series (prices are not)", "free; attribution required",
                                       "low", "CONDITIONAL", "metadata", "after the public-data archive exists"),
    "plotly/plotly.py": ("interactive charts", "none", "reports", "n/a", "free", "heavy JS", "DEFERRED", "metadata", ""),
    "ErTasselli/OpenTerminal": ("terminal-style finance UI", "public/ site", "design ideas", "n/a", "free", "none",
                                "RESEARCH_ONLY", "metadata", ""),
    "questdb/questdb": ("time-series database server", "bot-state JSON", "none at this volume", "n/a", "server cost",
                        "Java server to run", "REJECTED", "metadata", ""),
    "duckdb/duckdb": ("embedded analytical SQL", "none (0 files)", "query a Parquet archive of public data",
                      "public datasets only", "free", "low", "READY_FOR_PILOT", "metadata", "data-architecture.md choice"),
    "apache/arrow": ("Parquet / columnar data", "pyarrow arrives only via streamlit", "Parquet archive", "n/a", "free", "low",
                     "READY_FOR_PILOT", "repo_usage", "pairs with duckdb"),
    "fastapi/fastapi": ("API server", "static site + JSON", "none needed", "n/a", "hosting", "new surface", "REJECTED",
                        "metadata", ""),
    "pydantic/pydantic": ("data validation", "pandera + explicit validators", "message schemas", "n/a", "free", "low",
                          "DEFERRED", "metadata", ""),
    # F - Telegram and operations
    "aiogram/aiogram": ("async Telegram bot framework", "scripts/telegram_transport.py (requests)", "none: would compete with the sender",
                        "n/a", "free", "second sender", "REJECTED", "repo_usage", ""),
    "caronc/apprise": ("multi-channel notifications", "Telegram only", "other channels", "n/a", "free", "low", "DEFERRED",
                       "metadata", ""),
    "microsoft/playwright": ("browser tests", "scripts/ux_tasks.cjs, site_smoke.cjs", "none", "n/a", "free", "low",
                             "ALREADY_IN_USE", "repo_usage", ""),
    "getsentry/sentry-python": ("error monitoring", "workflow logs + ops digest", "error aggregation", "n/a",
                                "free tier limits", "sends data to a third party", "DEFERRED", "metadata", ""),
    "open-telemetry/opentelemetry-python": ("tracing", "none", "spans", "n/a", "free", "no long-running service", "DEFERRED",
                                            "metadata", ""),
    "prometheus/client_python": ("metrics endpoint", "none", "none (batch jobs)", "n/a", "free", "no service to scrape",
                                 "REJECTED", "metadata", ""),
    "encode/httpx": ("HTTP client", "requests + options_radar/http_fetch.py", "none needed", "n/a", "free", "churn", "REJECTED",
                     "metadata", ""),
    # G - portfolio
    "PyPortfolio/PyPortfolioOpt": ("portfolio optimisation", "none", "allocation", "n/a", "free", "out of scope", "DEFERRED",
                                   "metadata", ""),
    "dcajasn/Riskfolio-Lib": ("risk models", "none", "allocation", "n/a", "free", "out of scope", "DEFERRED", "metadata", ""),
    # H - caution
    "gammagrid/gammagrid": ("options GEX tooling", "free_gex_validation.py (context only)", "none for core",
                            "depends on its data feed", "free code", "AGPL-3.0", "REJECTED", "metadata",
                            "the owner's hosted GammaGrid connector is a separate service, not a runner source"),
    "kernc/backtesting.py": ("backtests", "walk-forward", "none", "n/a", "free", "AGPL-3.0", "REJECTED", "metadata",
                             "standing decision"),
    # tools run in this sweep
    "zizmorcore/zizmor": ("GitHub Actions security audit", "none before 2026-11-19", "370 findings over 75 workflows; 2 template injections fixed",
                          "n/a", "free", "low (read-only CI job)", "PARTIALLY_INTEGRATED", "ran", "security-audit.yml pilot"),
    "pypa/pip-audit": ("known-vulnerability audit", "none before 2026-11-19", "CVE check of runtime requirements (0 found)",
                       "n/a", "free", "low", "PARTIALLY_INTEGRATED", "ran", "security-audit.yml pilot"),
    "raimon49/pip-licenses": ("dependency licence listing", "none before 2026-11-19", "licence gate on runtime deps",
                              "n/a", "free", "low", "PARTIALLY_INTEGRATED", "ran", "security-audit.yml pilot"),
    "unionai-oss/pandera": ("dataframe validation", "options_radar/ohlcv_quality.py", "none", "n/a", "free", "low",
                            "ALREADY_IN_USE", "repo_usage", ""),
    "gerrymanoim/exchange_calendars": ("exchange calendars", "XNYS sessions everywhere", "none", "n/a", "free", "low",
                                       "ALREADY_IN_USE", "repo_usage", ""),
    "vollib/py_vollib": ("Black-Scholes IV and Greeks", "blackscholes as a test oracle", "IV/Greeks on licensed chains",
                         "needs a licensed option chain", "free", "last push 173 days", "CONDITIONAL", "metadata", ""),
}

# Extended-sweep finds worth a recorded decision (the rest of the 124 are metadata only).
EXTENDED: dict[str, tuple[str, str, str, str, str, str, str, str, str]] = {
    "python-telegram-bot/python-telegram-bot": ("Telegram framework", "telegram_transport.py (requests)", "none",
                                                "n/a", "free", "GPL-3.0", "REJECTED", "metadata", "copyleft; competing sender"),
    "skforecast/skforecast": ("forecasting with scikit-learn", "none", "forecasts", "n/a", "free", "no validated target",
                              "DEFERRED", "metadata", ""),
    "Nixtla/neuralforecast": ("neural forecasting", "none", "forecasts", "n/a", "compute", "heavy (torch)", "DEFERRED",
                              "metadata", ""),
    "interpretml/interpret": ("glass-box models", "none", "explainable models", "n/a", "free", "no matured sample",
                              "DEFERRED", "metadata", ""),
    "SEC-API-io/sec-api-python": ("client for a paid SEC API", "SEC direct", "none", "paid service terms", "paid",
                                  "subscription", "BLOCKED", "metadata", "paid; no purchases"),
    "greedo/python-xbrl": ("XBRL parsing", "sec_fundamentals.py (companyfacts JSON)", "none", "SEC public domain", "free",
                           "last push 211 days", "REJECTED", "metadata", ""),
    "srlcarlg/srl-python-indicators": ("volume profile indicators", "volume_liquidity.py, time_normalized_volume.py",
                                       "none proven", "n/a", "free", "64 stars, 321 days", "RESEARCH_ONLY", "metadata", ""),
}


def build(seed: dict[str, Any], extended: dict[str, Any]) -> dict[str, Any]:
    meta = {r["full_name"].lower(): r for r in seed.get("repositories", [])}
    meta.update({r["full_name"].lower(): r for r in extended.get("repositories", []) if r["full_name"].lower() not in meta})
    rows = []
    for source, table in (("seed", D), ("extended_sweep", EXTENDED)):
        for name, (purpose, overlap, new, rights, cost, risk, decision, evidence, note) in table.items():
            assert decision in STATUSES, (name, decision)
            m = meta.get(name.lower(), {})
            rows.append({
                "name": name.split("/", 1)[1], "repository": f"https://github.com/{m.get('full_name', name)}",
                "source": source, "purpose": purpose, "license": m.get("license", "NOT_VERIFIED"),
                "latest_push": (m.get("pushed_at") or "")[:10] or "NOT_VERIFIED",
                "stars": m.get("stargazers_count"), "fork": m.get("fork"), "archived": m.get("archived"),
                "existing_overlap": overlap, "new_capability": new, "data_rights": rights, "cost": cost,
                "risk": risk, "decision": decision, "evidence": evidence, "note": note,
            })
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    return {"schema": "ghazi.integration_candidates.v1", "as_of": seed.get("fetched_at"),
            "evidence_levels": ["metadata", "repo_usage", "read", "ran"],
            "decision_counts": dict(sorted(counts.items())), "candidates": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=Path, default=Path("docs/data/oss_seed_verified_2026-11-19.json"))
    parser.add_argument("--extended", type=Path, default=Path("docs/data/oss_candidates_extended_2026-11-19.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/data/integration_candidates_2026-11-19.json"))
    args = parser.parse_args()
    doc = build(json.loads(args.seed.read_text(encoding="utf-8")), json.loads(args.extended.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(doc["candidates"]), "candidates", doc["decision_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
