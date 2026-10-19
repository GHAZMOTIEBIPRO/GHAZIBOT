"""Publish non-priced source agreement *status*; never redistribute Massive-derived data."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def summarize(chart_report: Any, *, now: datetime, check: Any = None) -> dict:
    charts = chart_report if isinstance(chart_report, dict) else {}
    valid = (charts.get("schema") == "ghazi.stock_charts.v1"
             and charts.get("quote_execution_eligible") is False
             and charts.get("provider_source_family") == "yahoo")
    coverage = charts.get("coverage") if isinstance(charts.get("coverage"), dict) else {}
    price_count = coverage.get("with_valid_charts")
    if type(price_count) is not int or price_count < 0 or price_count > 1000:
        price_count = 0
    check = check if isinstance(check, dict) else {}
    # Only a fresh licensed cross-check (two attested, keyed vendors) can
    # verify; Yahoo charts never count as a licensed family.
    verified = (check.get("status") == "VERIFIED_LICENSED"
                and check.get("price_data_published") is False
                and isinstance(check.get("confirming_families"), list)
                and len(check["confirming_families"]) >= 2
                and _recent(check.get("generated_at"), now, hours=36))
    families = (["yahoo"] if valid and price_count else []) + (
        sorted(check["confirming_families"]) if verified else [])
    status = {
        "schema": "ghazi.source_consensus_status.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_charts_available": valid,
        "source_price_families": families,
        "source_charts_count": price_count if valid else 0,
        "independent_price_comparison": "VERIFIED_LICENSED" if verified else "NOT_VERIFIED",
        "licensed_independent_non_display_analysis": verified,
        "independent_confirmations": len(check["confirming_families"]) if verified else 0,
        "licensed_check_status": str(check.get("status") or "NOT_RUN"),
        "licensed_symbols_compared": check.get("symbols_compared") if verified else None,
        "licensed_median_divergence_bps": check.get("median_max_divergence_bps") if verified else None,
        "quote_execution_eligible": False,
        "massive_status": "LICENSE_AND_PRIVATE_NONDISPLAY_PERMISSION_REQUIRED",
        "massive_market_data_published": False,
        "option_bid_ask_verified": False,
        "research_only": True,
        "concordance_ratio": check.get("concordance_ratio") if verified else None,
        "price_data": None,
        "source_basis": (
            "Licensed daily-close cross-check between attested independent vendors; no prices published."
            if verified else
            "Chart publisher Yahoo-only. Licensed cross-check needs two keyed, owner-attested vendors."),
    }
    return status


def _recent(value: Any, now: datetime, *, hours: int) -> bool:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        return False
    age = (now - stamp).total_seconds()
    return -300 <= age <= hours * 3600


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--charts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--licensed-check", type=Path, default=None)
    args = parser.parse_args()
    check = {}
    if args.licensed_check and args.licensed_check.is_file():
        try:
            check = json.loads(args.licensed_check.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            check = {}
    source = {}
    if args.charts.is_file() and args.charts.stat().st_size <= 1_000_000:
        try:
            source = json.loads(args.charts.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    report = summarize(source, now=datetime.now(timezone.utc), check=check)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    print("Source independence:", report["independent_price_comparison"],
          "charts:", report["source_charts_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
