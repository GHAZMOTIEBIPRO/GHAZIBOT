"""Deterministic, fail-closed public trading-readiness verdict from real reports.

No market/API requests, no price or signal fabrication, no order execution.
Evidence on completed retrospective events ≠ out-of-sample tradable edge.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.trading_readiness.v1"
MAX_BYTES = 200_000
SOURCE_MINUTES = 180
ACCESS_HOURS = 24
HISTORICAL_DAYS = 30


def load(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return out.astimezone(timezone.utc) if out.tzinfo else None


def recent(report: dict, field: str, now: datetime, *, maximum: timedelta) -> bool:
    at = stamp(report.get(field))
    if at is None:
        return False
    delta = now - at
    return timedelta(0) <= delta <= maximum


def integer(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 1_000_000 else None


def number(value: Any) -> float | None:
    if type(value) not in {float, int}:
        return None
    n = float(value)
    return n if math.isfinite(n) else None


def build(data: dict[str, dict], *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("UTC-aware timestamp required")
    now = now.astimezone(timezone.utc)
    source = data.get("agreement") or {}
    charts = data.get("charts") or {}
    operations = data.get("operations") or {}
    access = data.get("access") or {}
    audit = data.get("audit") or {}
    walk = data.get("walk") or {}
    target = data.get("targets") or {}
    performance = data.get("options") or {}
    stage = data.get("stages") or {}
    strength = data.get("strength") or {}

    source_valid = (
        source.get("schema") == "ghazi.source_consensus_status.v1"
        and recent(source, "generated_at", now, maximum=timedelta(minutes=SOURCE_MINUTES))
    )
    charts_recent = (
        charts.get("schema") == "ghazi.stock_charts.v1"
        and recent(charts, "generated_at", now, maximum=timedelta(minutes=SOURCE_MINUTES))
    )
    chart_count = len(charts.get("symbols")) if isinstance(charts.get("symbols"), dict) else 0
    if chart_count > 100:
        chart_count = 0
    price_ready = bool(source_valid and charts_recent and chart_count > 0
                       and source.get("source_charts_available") is True
                       and source.get("independent_price_comparison") == "VERIFIED"
                       and (integer(source.get("independent_confirmations")) or 0) >= 2
                       and source.get("quote_execution_eligible") is True
                       and charts.get("execution_authority") is True)
    operations_ready = bool(
        recent(operations, "generated_at", now, maximum=timedelta(minutes=SOURCE_MINUTES))
        and operations.get("status") == "healthy"
        and isinstance(operations.get("coverage_diagnostics"), dict)
    )
    coverage = operations.get("coverage_diagnostics") or {}
    option_feed_ready = bool(
        operations_ready and coverage.get("options_execution_quote_ready") is True
        and coverage.get("options_trade_flow_ready") is True
        and (integer(coverage.get("option_live_primary_chains_reported")) or 0) > 0
        and source_valid and source.get("option_bid_ask_verified") is True
    )

    access_ready = bool(
        access.get("schema") == "ghazi.production_access.v1"
        and recent(access, "generated_at", now, maximum=timedelta(hours=ACCESS_HOURS))
        and access.get("site_http_accessible") is True
        and access.get("bot_api_authenticated") is True
    )

    stock_valid = audit.get("schema") == "ghazi.public_stock_outcomes.v1" and recent(
        audit, "generated_at", now, maximum=timedelta(days=HISTORICAL_DAYS)
    )
    stock_coverage = audit.get("coverage") if stock_valid else {}
    if not isinstance(stock_coverage, dict):
        stock_coverage = {}
    integrity = audit.get("close_time_integrity") if stock_valid else {}
    if not isinstance(integrity, dict):
        integrity = {}
    checked = integer(integrity.get("verified_version_2_records"))
    total = integer(stock_coverage.get("records"))
    stock_edge = bool(
        stock_valid and audit.get("proven_edge") is True
        and audit.get("verified_win_rate_pct") is not None
        and audit.get("promotion_gate", {}).get("live_promotion_allowed") is True
    )
    wf_gate = walk.get("gate") or {}
    walk_pass = bool(walk.get("mode") == "EXPANDING_SESSION_WALK_FORWARD"
                     and walk.get("research_passed") is True
                     and wf_gate.get("ready") is True
                     and walk.get("live_promotion_allowed") is True)

    targets_valid = (
        target.get("schema_version") == 1
        and recent(target, "generated_at", now, maximum=timedelta(days=HISTORICAL_DAYS))
    )
    cohort = ((target.get("cohorts") or {}).get("T1:INTRADAY_1D") or {}) if targets_valid else {}
    t1_n, t1_hit = integer(cohort.get("sample")), integer(cohort.get("hits"))
    if t1_n is None or t1_hit is None or t1_n == 0 or t1_hit > t1_n:
        t1_n, t1_hit = None, None
    # Historical hit-rate is not a trade win rate, option premium return or
    # forward-looking probability. Publish only this descriptive cohort.
    historical_t1_pct = round(100*t1_hit/t1_n, 2) if t1_n is not None else None

    perf_valid = (
        performance.get("schema_version") == 1
        and recent(performance, "generated_at", now, maximum=timedelta(days=HISTORICAL_DAYS))
    )
    counts = performance.get("counts") if perf_valid else {}
    if not isinstance(counts, dict):
        counts = {}
    options_samples = integer(counts.get("closed"))
    optcal = performance.get("calibration") if perf_valid else {}
    if not isinstance(optcal, dict):
        optcal = {}
    options_edge = bool(
        perf_valid and optcal.get("active") is True
        and (integer(optcal.get("training_sample_size")) or 0) >= 100
        and (options_samples or 0) >= 100
    )

    stage_valid = (stage.get("schema") == "ghazi.explosion_stage_evaluation.v1"
                   and recent(stage, "generated_at", now, maximum=timedelta(days=HISTORICAL_DAYS))
                   and stage.get("research_only") is True
                   and stage.get("decision_authority") is False)
    stages = stage.get("stages") if stage_valid else {}
    if not isinstance(stages, dict):
        stages = {}
    stage_rows = []
    for key in ("PRESSURE_BUILDING", "IGNITION", "EXPLOSION"):
        row = stages.get(key) or {}
        if not isinstance(row, dict):
            row = {}
        n = integer(row.get("decisive"))
        edge = number(row.get("expectancy_net_pct"))
        stage_rows.append({
            "name": key, "decisive": n,
            "modelled_net_expectancy_pct": round(edge, 3) if edge is not None else None,
            "measured_executable_pnl": False,
        })

    strength_value = number(strength.get("strength_score"))
    if not (
        strength.get("schema") == "ghazi.evidence_strength.v1"
        and strength.get("score_is_prediction_win_rate") is False
        and recent(strength, "generated_at", now, maximum=timedelta(days=HISTORICAL_DAYS))
        and strength_value is not None and 0 <= strength_value <= 100
    ):
        strength_value = None

    blockers = []
    if not price_ready:
        blockers.append("NO_LICENSED_INDEPENDENT_EXECUTION_PRICE")
    if not option_feed_ready:
        blockers.append("NO_EXECUTION_GRADE_OPTION_CHAIN_AND_FLOW")
    if not walk_pass:
        blockers.append("OUT_OF_SAMPLE_WALK_FORWARD_NOT_PASSED")
    if not stock_edge:
        blockers.append("NO_VERIFIED_STOCK_TRADABLE_EDGE")
    if not options_edge:
        blockers.append("NO_QUALIFIED_OPTION_PREMIUM_OUTCOMES")
    if not operations_ready:
        blockers.append("MARKET_OPERATIONS_NOT_HEALTHY")
    if not access_ready:
        blockers.append("SITE_OR_BOT_ACCESS_NOT_FRESHLY_VERIFIED")

    return {
        "schema": SCHEMA, "generated_at": now.isoformat(),
        "status": "NOT_TRADE_READY" if blockers else "RESEARCH_GATES_REPORTED_READY",
        # The output never authorizes brokerage trades even if all
        # research-grade checks become true. Strict per-contract V11 remains.
        "trade_recommendations_authorized": False,
        "automated_execution_allowed": False,
        "option_v11_execution_override": False,
        "data_source_staleness_limit_minutes": SOURCE_MINUTES,
        "checks": {
            "website_and_bot": access_ready,
            "independent_licensed_prices": price_ready,
            "market_operations": operations_ready,
            "options_execution_sources": option_feed_ready,
            "walk_forward_passed": walk_pass,
            "stock_edge_proven": stock_edge,
            "option_premium_outcomes_validated": options_edge,
        },
        "blockers": blockers,
        "historical_evidence": {
            "stock_audit_records": total,
            "individually_close_time_verified_records": checked,
            "walk_forward_research_passed": walk.get("research_passed") is True,
            "target_t1_intraday_matured": t1_n,
            "target_t1_intraday_hits": t1_hit,
            "target_t1_historical_hit_rate_pct": historical_t1_pct,
            "historical_target_calibration_ready_reported": bool(
                targets_valid and target.get("calibration_ready") is True
            ),
            "qualified_option_closed_samples": options_samples,
            "option_calibration_active": bool(perf_valid and optcal.get("active") is True),
            "stage_cost_model_expectancy": stage_rows,
            "research_data_strength_score": strength_value,
            "historical_hit_rate_is_profit_rate": False,
            "historical_hit_rate_is_forward_probability": False,
        },
        "scope_ar": (
            "النتائج التاريخية وشموع Yahoo القديمة ليست دليل ربح أو أسعار تنفيذ. "
            "درجة البيانات ليست نسبة نجاح. لا يوجد اعتماد تداول تلقائي، "
            "ولا تجاوز لبوابة V11، ولا توصية CALL/PUT."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish real evidence, never guess trading reliability.")
    for name in ("agreement", "charts", "operations", "access", "audit",
                 "walk", "targets", "options", "stages", "strength"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {key: load(getattr(args, key)) for key in (
        "agreement", "charts", "operations", "access", "audit",
        "walk", "targets", "options", "stages", "strength"
    )}
    result = build(inputs, now=datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(args.output)
    print("GHAZI trading-readiness:", result["status"],
          "blocked checks:", len(result["blockers"]),
          "historical T1 sample:", result["historical_evidence"]["target_t1_intraday_matured"])


if __name__ == "__main__":
    main()
