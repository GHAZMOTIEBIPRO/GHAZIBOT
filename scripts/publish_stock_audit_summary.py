"""Safe public digest of the existing independent stock outcome audit.

Never promote a historical 5m price-path audit into realized live P/L.
Ambiguous/nondecisive/pending/unavailable observations remain visible.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def safe_int(value: object) -> int:
    try:
        n = int(value)  # Counts only, never raw quote prices.
        return max(0, min(n, 10_000_000))
    except (TypeError, ValueError, OverflowError):
        return 0


def build_summary(audit: dict, *, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("report time must be timezone-aware")
    if audit.get("decision_authority") is not False:
        raise ValueError("input lacks research-only authority guard")
    if audit.get("mode") != "HISTORICAL_5M_OUTCOME_AUDIT":
        raise ValueError("unknown audit measurement type")
    source_coverage = audit.get("coverage") or {}
    if not isinstance(source_coverage, dict):
        raise ValueError("malformed coverage")
    counts = {key: safe_int(source_coverage.get(key)) for key in (
        "records", "records_total", "eligible_records", "covered_60m", "decisive",
        "ambiguous", "non_decisive", "pending", "unavailable", "invalid_session",
        "independent_60m_sessions",
    )}
    if counts["covered_60m"] > counts["records"]:
        raise ValueError("covered_60m cannot exceed eligible records")
    gate = audit.get("promotion_gate") if isinstance(audit.get("promotion_gate"), dict) else {}
    return {
        "schema": "ghazi.public_stock_outcomes.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "mode": "HISTORICAL_5M_OUTCOME_AUDIT",
        "source": "existing GHAZIBOT free Yahoo stock outcome auditor",
        "coverage": counts,
        "promotion_gate": {
            "coverage_ready": gate.get("coverage_ready") is True,
            "minimum_independent_sessions": safe_int(gate.get("minimum_independent_sessions")),
            "minimum_60m_coverage_pct": gate.get("minimum_60m_coverage_pct"),
            "live_promotion_allowed": False,
        },
        "proven_edge": False,
        "verified_win_rate_pct": None,
        "realized_portfolio_pnl": False,
        "annualized_returns_claimed": False,
        "decision_authority": False,
        "reason_ar": (
            "التقرير يقيس نتائج بحثية بعد وقت الإشارة باستخدام شموع Yahoo التاريخية؛ "
            "لا يوجد إثبات لنتائج تنفيذ حقيقي أو معدل ربح قابل للتعميم. "
            "الحالات الغامضة وغير المكتملة ظاهرة ولا تُحذف من جودة العينة."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_summary(json.loads(args.audit.read_text(encoding="utf-8")),
                           now=datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    tmp.replace(args.output)
    print("Public stock audit summary:", report["coverage"])


if __name__ == "__main__":
    raise SystemExit(main())
