"""Nasdaq-listed securities from Nasdaq's own symbol directory file (nasdaqlisted.txt).

Rights: opened by Nasdaq's product notice for "Nasdaq Listed" ("without restriction or any
further licensing requirement", options_radar/source_permissions.PRODUCT_GRANTS). Only this
file is read; otherlisted.txt and the other directory files stay closed (PRODUCT_UNRESOLVED).

Counts are kept apart: securities (rows), test issues (excluded), ETFs, equity securities,
other securities (warrants, units, rights, preferred, notes) and companies (distinct issuers
of equity securities; several share classes of one issuer count once). No prices, no market
caps. The Financial Status field (Nasdaq Security Status) becomes a risk flag; when a flag
first appears its first_seen_at is this run's time, carried in later runs; flags already
present when tracking starts keep first_seen_at = null.

One request per run; a file that fails validation leaves the previous output untouched.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

SCHEMA = "ghazi.nasdaq_listed.v1"
HEADER = ["Symbol", "Security Name", "Market Category", "Test Issue", "Financial Status", "Round Lot Size",
          "ETF", "NextShares"]
MIN_ROWS = 2500
SYMBOL = re.compile(r"^[A-Z]{1,5}(?:[.$][A-Z]{1,2})?$")
UA = {"User-Agent": "GHAZI-RADAR-symbol-directory/1.1 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
CATEGORY = {"Q": "NASDAQ Global Select Market", "G": "NASDAQ Global Market", "S": "NASDAQ Capital Market"}
STATUS = {  # Nasdaq Symbol Directory definitions page
    "D": ("Deficient", "لا يستوفي معايير الإدراج المستمر"),
    "E": ("Delinquent", "متأخر في تقديم الإفصاحات الدورية"),
    "Q": ("Bankrupt", "في إجراءات إفلاس"),
    "G": ("Deficient and Bankrupt", "لا يستوفي المعايير وفي إجراءات إفلاس"),
    "H": ("Deficient and Delinquent", "لا يستوفي المعايير ومتأخر في الإفصاحات"),
    "J": ("Delinquent and Bankrupt", "متأخر في الإفصاحات وفي إجراءات إفلاس"),
    "K": ("Deficient, Delinquent and Bankrupt", "لا يستوفي المعايير ومتأخر وفي إجراءات إفلاس"),
}
EQUITY = re.compile(r"(common stock|capital stock|ordinary shares?|american depositary shares?|common shares?|"
                    r"class [a-z] (common )?(stock|shares?)|subordinate voting shares)", re.IGNORECASE)


class FileRejected(ValueError):
    """The fetched file does not look like the Nasdaq-listed directory."""


def _gates():
    path = Path(__file__).resolve().parents[1] / "options_radar" / "source_permissions.py"
    spec = importlib.util.spec_from_file_location("ghazi_source_permissions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_name(name: str) -> tuple[str, str]:
    """'Alphabet Inc. - Class A Common Stock' -> ('Alphabet Inc.', 'Class A Common Stock')."""
    issuer, _, security = name.partition(" - ")
    return issuer.strip(), security.strip()


def parse(text: str) -> tuple[list[dict[str, Any]], str | None, int]:
    lines = [x for x in text.splitlines() if x.strip()]
    if not lines or lines[0].split("|") != HEADER:
        raise FileRejected("unexpected header")
    created = None
    rows, tests = [], 0
    for line in lines[1:]:
        if line.startswith("File Creation Time:"):
            # Documented footer: "File Creation Time: 1217200717:03" = mmddyyyy hh:mm (New York).
            m = re.search(r"(\d{8})(\d{2}):?(\d{2})", line)
            if m:
                ny = datetime.strptime("".join(m.groups()), "%m%d%Y%H%M").replace(tzinfo=ZoneInfo("America/New_York"))
                created = ny.astimezone(timezone.utc).isoformat()
            continue
        f = line.split("|")
        if len(f) != len(HEADER):
            raise FileRejected("row with wrong field count")
        symbol, name, cat, test, fin, _lot, etf, _next = (x.strip() for x in f)
        if test == "Y":
            tests += 1
            continue
        if not SYMBOL.match(symbol):
            continue
        issuer, security = split_name(name)
        rows.append({"symbol": symbol, "issuer": issuer[:90], "security": security[:60], "category": cat,
                     "financial_status": fin or "N", "etf": etf == "Y",
                     "equity": etf != "Y" and bool(EQUITY.search(security))})
    if len(rows) < MIN_ROWS:
        raise FileRejected(f"{len(rows)} rows (expected at least {MIN_ROWS})")
    if created is None:
        raise FileRejected("no File Creation Time footer")
    return rows, created, tests


def carry_flags(rows: list[dict[str, Any]], previous: Any, now: datetime) -> tuple[list[dict[str, Any]], str]:
    tracking = isinstance(previous, dict) and previous.get("schema") == SCHEMA
    known = {(f["symbol"], f["status"]): f.get("first_seen_at") for f in (previous or {}).get("status_flags") or []
             if isinstance(f, dict)} if tracking else {}
    flags = []
    for r in rows:
        status = r["financial_status"]
        if status in STATUS:
            key = (r["symbol"], status)
            first = known.get(key) if key in known else (now.isoformat() if tracking else None)
            flags.append({"symbol": r["symbol"], "issuer": r["issuer"], "status": status,
                          "status_en": STATUS[status][0], "status_ar": STATUS[status][1],
                          "first_seen_at": first,
                          "first_seen_basis": ("CARRIED" if key in known else "THIS_RUN") if tracking else "BEFORE_TRACKING"})
    since = (previous or {}).get("tracking_since") if tracking else now.isoformat()
    return flags, since or now.isoformat()


def build(text: str, now: datetime, previous: Any = None) -> dict[str, Any]:
    rows, created, tests = parse(text)
    equities = [r for r in rows if r["equity"]]
    flags, since = carry_flags(rows, previous, now)
    by_cat: dict[str, int] = {}
    for r in equities:
        by_cat[CATEGORY.get(r["category"], r["category"])] = by_cat.get(CATEGORY.get(r["category"], r["category"]), 0) + 1
    gates = _gates()
    grant = gates.PRODUCT_GRANTS["nasdaqtrader_nasdaq_listed"]
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "file_created_at": created,
        "source": {"url": grant["url"], "notice_url": grant["notice_url"], "notice": grant["evidence"],
                   "evidence_run": grant["evidence_run"]},
        "counts": {
            "securities": len(rows),
            "test_issues_excluded": tests,
            "etfs": sum(r["etf"] for r in rows),
            "equity_securities": len(equities),
            "other_securities": sum(1 for r in rows if not r["etf"] and not r["equity"]),
            "companies": len({r["issuer"].lower() for r in equities}),
            "equity_by_market_category": by_cat,
            "status_flags": len(flags),
        },
        "scope_note_ar": ("أوراق مدرجة في Nasdaq فقط (لا تشمل NYSE وغيرها). الشركة الواحدة قد تملك أكثر من ورقة. "
                          "لا أسعار ولا قيم سوقية؛ فئة السوق ليست تصنيف حجم."),
        "fields": ["symbol", "issuer", "security", "category", "financial_status", "etf", "equity"],
        "rows": [[r["symbol"], r["issuer"], r["security"], r["category"], r["financial_status"], int(r["etf"]),
                  int(r["equity"])] for r in sorted(rows, key=lambda r: r["symbol"])],
        "status_flags": sorted(flags, key=lambda f: f["symbol"]),
        "tracking_since": since,
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }


def fetch(session: Any = requests) -> str:
    gates = _gates()
    if not gates.product_allowed("nasdaqtrader_nasdaq_listed"):
        raise FileRejected("product not granted")
    r = session.get(gates.PRODUCT_GRANTS["nasdaqtrader_nasdaq_listed"]["url"], timeout=30, headers=UA)
    r.raise_for_status()
    return r.text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = None
    if args.output.is_file():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    try:
        report = build(fetch(), datetime.now(timezone.utc), previous)
    except (requests.RequestException, FileRejected, ValueError) as exc:
        print(json.dumps({"status": "REJECTED_KEPT_PREVIOUS", "error": f"{type(exc).__name__}: {exc}"[:200]}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"file_created_at": report["file_created_at"], **report["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
