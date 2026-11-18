"""Reproducible open-source candidate review for GHAZI RADAR.

Two steps:
  fetch  -> query GitHub repository search (via the `gh` CLI) for each category, paced, and
            write the raw metadata snapshot (no code is downloaded or executed).
  score  -> rank the snapshot with a fixed, documented formula and print a Markdown table.

The score measures fit and risk, not quality of the project:
  licence      MIT/BSD/Apache/ISC/Unlicense 3, MPL/LGPL/EPL 1, GPL/AGPL/NOASSERTION/none 0
  maintenance  last push <=90 days 3, <=365 days 2, <=730 days 1, older or archived 0
  adoption     stars >=10000 3, >=1000 2, >=200 1, else 0
  stack fit    Python 2, TypeScript/JavaScript 1, other 0
  total        licence + maintenance + adoption + stack fit (0..11)

A project whose licence scores 0 may still be studied as a concept but its code must not
enter the core (AGENTS.md open-source policy). Standing repository decisions override the
score (see STANDING).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATEGORIES: dict[str, tuple[str, ...]] = {
    "market_data": ("topic:market-data stars:>200",),
    "intraday_history": ("topic:historical-data stars:>100", "intraday in:name,description stars:>200"),
    "technical_analysis": ("topic:technical-analysis stars:>300",),
    "fibonacci": ("fibonacci trading", "fibonacci retracement"),
    "market_structure": ("topic:market-microstructure", "topic:orderbook stars:>200"),
    "options_greeks": ("topic:options-pricing stars:>50", "topic:black-scholes stars:>50"),
    "gamma_exposure": ("gamma exposure options",),
    "volatility_forecast": ("topic:volatility stars:>50", "garch in:name,description stars:>50"),
    "institutional_13f": ("13f in:name,description stars:>10",),
    "insider_trades": ("insider trading in:name,description stars:>10",),
    "sec_filings": ("topic:sec-edgar", "edgar in:name,description stars:>200"),
    "news_catalysts": ("topic:financial-news stars:>30", "stock news sentiment in:description stars:>100"),
    "ai_research_agents": ("llm trading in:description stars:>300", "topic:fingpt"),
    "signal_validation": ("factor in:name,description topic:quantitative-finance stars:>200",),
    "backtesting": ("topic:backtesting stars:>1000",),
    "walk_forward": ("walk forward in:description stars:>20",),
    "pine_script": ("topic:pinescript stars:>100",),
    "anomaly_detection": ("anomaly detection stock in:description stars:>20",),
    "risk_sizing": ("topic:portfolio-optimization stars:>300", "position sizing in:description stars:>20"),
    "dashboards": ("trading dashboard stars:>300", "topic:stock-dashboard stars:>30"),
}

NAMED = (
    "OpenBB-finance/OpenBB", "polakowo/vectorbt", "QuantConnect/Lean", "nautechsystems/nautilus_trader",
    "ranaroussi/quantstats", "lballabio/QuantLib", "TA-Lib/ta-lib-python", "dgunning/edgartools",
    "TauricResearch/TradingAgents", "AI4Finance-Foundation/FinRL", "kernc/backtesting.py",
    "stefan-jansen/zipline-reloaded", "dcajasn/Riskfolio-Lib", "robertmartin8/PyPortfolioOpt",
    "stefan-jansen/alphalens-reloaded", "domokane/FinancePy", "vollib/py_vollib",
    "WallStreetPete/awesome-open-source-trading",
)

PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "Unlicense", "0BSD", "BSL-1.0"}
WEAK_COPYLEFT = {"MPL-2.0", "LGPL-2.1", "LGPL-3.0", "EPL-2.0"}

# Repository decisions that override the formula (docs/OSS_SELECTION_2026-10-29.md, CLAUDE.md).
STANDING: dict[str, str] = {
    "kernc/backtesting.py": "AGPL-3.0: not integrated (standing decision)",
    "TA-Lib/ta-lib-python": "needs the C library build: not added; pandas-ta-classic is the reference",
    "mementum/backtrader": "GPL-3.0: concept only",
    "ranaroussi/yfinance": "Yahoo terms block automated access: never a data source",
    "dpguthrie/yahooquery": "Yahoo terms block automated access: never a data source",
}

FIELDS = ("full_name", "html_url", "description", "language", "stargazers_count", "pushed_at",
          "archived", "fork", "open_issues_count")

# Relevance screen: GHAZI RADAR covers U.S. equities, ETFs, indices and listed options from lawful
# sources. A repository matching one of these patterns (name or description, case-insensitive)
# is excluded with the stated reason. The screen is a filter, not a judgement of the project.
SCREEN: tuple[tuple[str, str], ...] = (
    (r"crypto|bitcoin|binance|ethereum|defi|uniswap|ccxt|blockchain|web3|solana|hummingbot",
     "crypto venues, outside scope"),
    (r"a-share|a share|股|china|chinese|tushare|akshare|\bcn\w*equity|eastmoney|baostock",
     "China A-share markets, outside scope"),
    (r"yfinance|yahoo|finviz|tradingview[- ]screener|investing\.com|stooq|nasdaq\.com",
     "reads a source whose terms block automated access"),
    (r"paywall|bypass|12ft", "circumvention tool, never used"),
    (r"forex|\bfx\b|metatrader|\bmt4\b|\bmt5\b", "FX / MetaTrader, outside scope"),
)


def _search(query: str, per_page: int = 30) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["gh", "api", "-X", "GET", "search/repositories", "-f", f"q={query}", "-f", "sort=stars",
         "-f", f"per_page={per_page}"],
        check=False, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode:
        print(f"search failed for {query!r}: {proc.stderr.strip()[:200]}", file=sys.stderr)
        return []
    items = json.loads(proc.stdout).get("items") or []
    rows = []
    for item in items:
        row = {key: item.get(key) for key in FIELDS}
        row["license"] = (item.get("license") or {}).get("spdx_id") or "NONE"
        rows.append(row)
    return rows


def fetch(output: Path, *, pause: float = 4.0, per_page: int = 30) -> dict[str, Any]:
    repos: dict[str, dict[str, Any]] = {}
    for category, queries in CATEGORIES.items():
        for query in queries:
            for row in _search(query, per_page):
                entry = repos.setdefault(row["full_name"], {**row, "categories": []})
                if category not in entry["categories"]:
                    entry["categories"].append(category)
            time.sleep(pause)
    # Named projects are resolved one by one by repository name, so renamed repositories
    # (GitHub search does not follow redirects for repo: qualifiers) are still found.
    # Forks are searched too (zipline-reloaded and alphalens-reloaded are forks). An exact
    # owner/name match wins; otherwise only a same-named repository with >=100 stars is accepted
    # and recorded as resolved from the requested name, never a low-star copy.
    for name in NAMED:
        short = name.split("/", 1)[1]
        candidates = _search(f"{short} in:name fork:true", 20)
        exact = [row for row in candidates if row["full_name"].lower() == name.lower()]
        renamed = [row for row in candidates
                   if row["full_name"].split("/", 1)[1].lower() == short.lower()
                   and int(row.get("stargazers_count") or 0) >= 100]
        match = (exact or renamed or [None])[0]
        if match is None:
            print(f"named project not found: {name}", file=sys.stderr)
        else:
            entry = repos.setdefault(match["full_name"], {**match, "categories": []})
            entry["named"] = True
            if match["full_name"].lower() != name.lower():
                entry["resolved_from"] = name
        time.sleep(pause)
    snapshot = {
        "schema": "ghazi.oss_review.v1",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "method": "GitHub repository search, sorted by stars, metadata only",
        "queries": {category: list(queries) for category, queries in CATEGORIES.items()},
        "named": list(NAMED),
        "repositories": sorted(repos.values(), key=lambda r: r["full_name"].lower()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return snapshot


def score(row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    licence = str(row.get("license") or "NONE")
    licence_score = 3 if licence in PERMISSIVE else 1 if licence in WEAK_COPYLEFT else 0
    pushed = row.get("pushed_at")
    try:
        age = (now - datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))).days
    except ValueError:
        age = None
    if row.get("archived") or age is None:
        maintenance = 0
    else:
        maintenance = 3 if age <= 90 else 2 if age <= 365 else 1 if age <= 730 else 0
    stars = int(row.get("stargazers_count") or 0)
    adoption = 3 if stars >= 10000 else 2 if stars >= 1000 else 1 if stars >= 200 else 0
    language = str(row.get("language") or "")
    stack = 2 if language == "Python" else 1 if language in {"TypeScript", "JavaScript"} else 0
    return {
        "full_name": row["full_name"],
        "licence": licence,
        "licence_score": licence_score,
        "maintenance": maintenance,
        "days_since_push": age,
        "adoption": adoption,
        "stack": stack,
        "total": licence_score + maintenance + adoption + stack,
        "core_allowed": licence_score == 3,
        "standing_decision": STANDING.get(row["full_name"]),
    }


def screen(repo: dict[str, Any]) -> str | None:
    """Exclusion reason for an out-of-scope or non-compliant repository, else None."""
    text = f"{repo.get('full_name') or ''} {repo.get('description') or ''}".lower()
    for pattern, reason in SCREEN:
        if re.search(pattern, text):
            return reason
    return None


def ranked(snapshot: dict[str, Any], *, now: datetime) -> list[dict[str, Any]]:
    rows = []
    for repo in snapshot.get("repositories", []):
        # Forks are only kept when explicitly named (maintained forks such as zipline-reloaded).
        if repo.get("fork") and not repo.get("named"):
            continue
        rows.append({**score(repo, now=now), "categories": repo.get("categories", []),
                     "named": bool(repo.get("named")), "language": repo.get("language"),
                     "stars": repo.get("stargazers_count"), "url": repo.get("html_url"),
                     "excluded": screen(repo)})
    return sorted(rows, key=lambda r: (-r["total"], -(r["stars"] or 0), r["full_name"].lower()))


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| # | Repository | Categories | Licence | Push age (d) | Stars | Lang | L/M/A/S | Total | Core code allowed |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for index, row in enumerate(rows, 1):
        lines.append(
            f"| {index} | [{row['full_name']}]({row['url']}) | {', '.join(row['categories']) or 'named'} | "
            f"{row['licence']} | {row['days_since_push']} | {row['stars']} | {row['language'] or '-'} | "
            f"{row['licence_score']}/{row['maintenance']}/{row['adoption']}/{row['stack']} | {row['total']} | "
            f"{'yes' if row['core_allowed'] and not row['standing_decision'] else 'no'} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--snapshot", type=Path, required=True)
    s.add_argument("--as-of", help="ISO time used for push age (defaults to the snapshot time)")
    s.add_argument("--top", type=int, default=0, help="print only the first N kept rows")
    args = parser.parse_args()
    if args.command == "fetch":
        snap = fetch(args.output)
        print(f"{len(snap['repositories'])} repositories written to {args.output}")
        return
    snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat((args.as_of or snap["fetched_at"]).replace("Z", "+00:00"))
    rows = ranked(snap, now=as_of)
    kept = [row for row in rows if not row["excluded"] or row["named"]]
    reasons: dict[str, int] = {}
    for row in rows:
        if row["excluded"] and not row["named"]:
            reasons[row["excluded"]] = reasons.get(row["excluded"], 0) + 1
    print(f"<!-- scored {len(rows)}; kept after relevance screen {len(kept)}; excluded {reasons} -->")
    print(markdown(kept[: args.top] if args.top else kept))


if __name__ == "__main__":
    main()
