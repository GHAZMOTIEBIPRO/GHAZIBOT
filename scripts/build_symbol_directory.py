"""Leaders directory: current S&P 500 members with name, sector and SEC CIK.

Source (probe run 40266602180, 2026-10-26): github.com/datasets/s-and-p-500-companies,
data/constituents.csv. Its datapackage names the upstream as Wikipedia's "List of S&P 500
companies"; the packaging is ODC-PDDL-1.0 and the upstream text is CC BY-SA 4.0, so the
published file carries attribution and the CC BY-SA notice. The data commit SHA and date
are recorded so every row can be traced to the snapshot it came from.

Scope: the CURRENT member list only. It is not point-in-time membership and must not be
used for historical tests (survivorship). It carries no prices and no market caps.

Fail closed: a file that does not look like the expected list (header, 480-520 rows,
valid symbols, CIKs) is rejected and the previous published file is left untouched.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SCHEMA = "ghazi.symbol_directory.v1"
REPO = "datasets/s-and-p-500-companies"
DATA_PATH = "data/constituents.csv"
CSV_URL = f"https://raw.githubusercontent.com/{REPO}/{{ref}}/{DATA_PATH}"
COMMITS_URL = f"https://api.github.com/repos/{REPO}/commits?path={DATA_PATH}&per_page=1"
UPSTREAM = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HEADER = ("Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "CIK", "Date added")
MIN_ROWS, MAX_ROWS = 480, 520
SYMBOL = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")
UA = {"User-Agent": "GHAZI-RADAR-symbol-directory/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
SECTOR_AR = {
    "Information Technology": "تقنية المعلومات", "Health Care": "الرعاية الصحية", "Financials": "المالية",
    "Consumer Discretionary": "السلع الكمالية", "Communication Services": "خدمات الاتصالات",
    "Industrials": "الصناعة", "Consumer Staples": "السلع الأساسية", "Energy": "الطاقة",
    "Utilities": "المرافق", "Real Estate": "العقار", "Materials": "المواد",
}


class DirectoryRejected(ValueError):
    """The fetched file does not look like the expected member list."""


def parse(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    missing = [h for h in HEADER if h not in (reader.fieldnames or [])]
    if missing:
        raise DirectoryRejected(f"missing columns: {missing}")
    rows: dict[str, dict[str, Any]] = {}
    for raw in reader:
        symbol = str(raw.get("Symbol") or "").strip().upper()
        cik = str(raw.get("CIK") or "").strip()
        sector = str(raw.get("GICS Sector") or "").strip()
        if not SYMBOL.match(symbol) or not cik.isdigit() or sector not in SECTOR_AR:
            raise DirectoryRejected(f"invalid row for {symbol or '?'}")
        rows[symbol] = {
            "symbol": symbol,
            "name": str(raw.get("Security") or "").strip()[:80],
            "sector": sector,
            "sector_ar": SECTOR_AR[sector],
            "sub_industry": str(raw.get("GICS Sub-Industry") or "").strip()[:80],
            "cik": cik.zfill(10),
            "date_added": str(raw.get("Date added") or "").strip()[:10] or None,
        }
    if not MIN_ROWS <= len(rows) <= MAX_ROWS:
        raise DirectoryRejected(f"{len(rows)} rows (expected {MIN_ROWS}-{MAX_ROWS})")
    return sorted(rows.values(), key=lambda r: r["symbol"])


def build(text: str, commit: dict[str, str], now: datetime) -> dict[str, Any]:
    rows = parse(text)
    sectors: dict[str, int] = {}
    for row in rows:
        sectors[row["sector"]] = sectors.get(row["sector"], 0) + 1
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "status": "AVAILABLE",
        "universe": "S&P 500 current members",
        "point_in_time": False,
        "count": len(rows),
        # Rows are securities; several share classes of one company (e.g. GOOGL/GOOG) share a CIK.
        "counts": {"securities": len(rows), "companies": len({r["cik"] for r in rows})},
        "sectors": dict(sorted(sectors.items(), key=lambda kv: -kv[1])),
        "source": {
            "dataset": f"https://github.com/{REPO}",
            "data_commit_sha": commit.get("sha"),
            "data_commit_date": commit.get("date"),
            "upstream": UPSTREAM,
            "packaging_license": "ODC-PDDL-1.0",
            "upstream_license": "CC BY-SA 4.0 (Wikipedia text)",
            "attribution": "Wikipedia contributors, \"List of S&P 500 companies\" (CC BY-SA 4.0), "
                           "via the datasets/s-and-p-500-companies data package",
        },
        "use": {
            "allowed_here": ["symbol search", "leaders tab membership", "sector label", "SEC CIK link"],
            "not_for": ["historical tests (current members only, survivorship)", "prices", "market cap", "index weights"],
            "note_ar": "قائمة الأعضاء الحاليين فقط؛ لا تصلح لاختبار تاريخي ولا تحمل أسعارًا أو قيمًا سوقية أو أوزانًا.",
        },
        "symbols": rows,
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }


def fetch(session: Any = requests) -> tuple[str, dict[str, str]]:
    commits = session.get(COMMITS_URL, timeout=20, headers={"Accept": "application/vnd.github+json", **UA})
    commits.raise_for_status()
    head = (commits.json() or [{}])[0]
    commit = {"sha": str(head.get("sha") or ""), "date": str(((head.get("commit") or {}).get("committer") or {}).get("date") or "")}
    if not re.fullmatch(r"[0-9a-f]{40}", commit["sha"]):
        raise DirectoryRejected("no data commit found")
    # Read the exact commit, so the recorded SHA is the snapshot that was parsed.
    response = session.get(CSV_URL.format(ref=commit["sha"]), timeout=20, headers=UA)
    response.raise_for_status()
    return response.text, commit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        text, commit = fetch()
        report = build(text, commit, datetime.now(timezone.utc))
    except (requests.RequestException, DirectoryRejected, ValueError) as exc:
        # Keep the previous published file; the failure is visible in the job.
        print(json.dumps({"status": "REJECTED_KEPT_PREVIOUS", "error": f"{type(exc).__name__}: {exc}"[:200]}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"status": report["status"], "count": report["count"],
                      "data_commit_date": commit["date"], "sectors": len(report["sectors"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
