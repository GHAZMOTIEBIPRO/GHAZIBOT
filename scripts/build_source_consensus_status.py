"""Publish non-priced source agreement *status*; never redistribute Massive-derived data."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def summarize(chart_report: Any, *, now: datetime) -> dict:
    charts = chart_report if isinstance(chart_report, dict) else {}
    valid = (charts.get("schema") == "ghazi.stock_charts.v1"
             and charts.get("quote_execution_eligible") is False
             and charts.get("provider_source_family") == "yahoo")
    coverage = charts.get("coverage") if isinstance(charts.get("coverage"), dict) else {}
    price_count = coverage.get("with_valid_charts")
    if type(price_count) is not int or price_count < 0 or price_count > 1000:
        price_count = 0
    return {
        "schema": "ghazi.source_consensus_status.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_charts_available": valid,
        "source_price_families": ["yahoo"] if valid and price_count else [],
        "source_charts_count": price_count if valid else 0,
        "independent_price_comparison": "NOT_VERIFIED",
        "independent_confirmations": 0,
        "quote_execution_eligible": False,
        "massive_status": "LICENSE_AND_PRIVATE_NONDISPLAY_PERMISSION_REQUIRED",
        "massive_market_data_published": False,
        "option_bid_ask_verified": False,
        "research_only": True,
        "concordance_ratio": None,
        "price_data": None,
        "source_basis": ("Chart publisher Yahoo-only. Additional API bridges are "
                         "disabled until data-use authorization is confirmed."),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--charts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = {}
    if args.charts.is_file() and args.charts.stat().st_size <= 1_000_000:
        try:
            source = json.loads(args.charts.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    report = summarize(source, now=datetime.now(timezone.utc))
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
