"""Independent public evidence verdict built only from already-redacted reports.

No quotes, keys, probabilities or broker permissions are inferred from this
module. Its role is to prevent a fresh report or a passing CI build from being
mistaken for a verified live trading signal.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = "ghazi.trust_verdict.v1"
MAX_REPORT_DIFF_MINUTES = 20
MAX_REPORT_AGE_MINUTES = 120


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _section(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 2) if denominator else None


def assess(latest: Any, status: Any, health: Any = None, *,
           now: datetime | None = None) -> dict[str, Any]:
    """Decision-bound provenance: never let a metric from a proxy imply P&L."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    stamp_latest = _time(latest.get("generated_at")) if isinstance(latest, dict) else None
    stamp_status = _time(status.get("generated_at")) if isinstance(status, dict) else None
    generated = min((x for x in (stamp_latest, stamp_status) if x), default=None)
    mismatched = bool(
        stamp_latest and stamp_status
        and abs((stamp_latest - stamp_status).total_seconds()) > MAX_REPORT_DIFF_MINUTES * 60)
    age = ((now.astimezone(timezone.utc) - generated).total_seconds() / 60
           if generated else None)
    reports_fresh = bool(
        age is not None and -5 <= age <= MAX_REPORT_AGE_MINUTES and not mismatched)
    snapshot = latest if isinstance(latest, dict) else {}
    report = status if isinstance(status, dict) else {}
    performance = _section(snapshot, "performance")
    calibration = _section(snapshot, "calibration")
    coverage = _section(report, "coverage_diagnostics")
    counts = _section(report, "row_counts")
    quality = _section(report, "quality_counts")
    summary = _section(snapshot, "summary")
    readiness = _section(report, "option_provider_readiness")
    network = _section(snapshot, "source_network")
    network_summary = _section(network, "summary")
    checks = _section(health, "checks")

    evaluated = _count(performance.get("path_evaluated"))
    success = _count(performance.get("successful"))
    stop = _count(performance.get("stopped_out"))
    ambiguous = _count(performance.get("ambiguous"))
    option_basis = _count(performance.get("option_contract_basis"))
    proxy_basis = _count(performance.get("underlying_proxy_basis"))
    history_valid = bool(
        evaluated is not None and success is not None and stop is not None
        and ambiguous is not None and option_basis is not None
        and proxy_basis is not None and
        success + stop + ambiguous <= evaluated and
        option_basis + proxy_basis <= evaluated)
    option_qualified = bool(
        report.get("status") == "healthy"
        and coverage.get("options_execution_quote_ready") is True
        and coverage.get("options_trade_flow_ready") is True
        and readiness.get("production_quote_ready") is True
        and readiness.get("production_flow_ready") is True
        and (_count(counts.get("options")) or 0) > 0
        and (_count(quality.get("critical_errors")) or 0) == 0
        and checks.get("critical_pipeline_ok") is True)
    stock_families = coverage.get("stock_primary_non_yahoo_families_reported")
    stock_verified = (isinstance(stock_families, list) and len(set(
        x for x in stock_families if isinstance(x, str) and x)) >= 2
        and (_count(counts.get("stocks")) or 0) > 0
        and checks.get("critical_pipeline_ok") is True)
    # An option price source is independent of an exchange ownership proof
    # and a research-calibration sample is not evidence of fills.
    blockers: list[str] = []
    if not reports_fresh:
        blockers.append("REPORT_STALE_OR_INCONSISTENT_TIMESTAMPS")
    if checks.get("critical_pipeline_ok") is not True:
        blockers.append("CRITICAL_PIPELINE_NOT_HEALTHY")
    if not stock_verified:
        blockers.append("NO_INDEPENDENT_LICENSED_STOCK_PRICE_CROSSCHECK")
    if not option_qualified:
        blockers.append("NO_EXECUTION_GRADE_OPTION_QUOTE_AND_FLOW")
    if not history_valid:
        blockers.append("OUTCOME_COUNTERS_INVALID")
    if not history_valid or not option_basis:
        blockers.append("NO_VALIDATED_OPTION_PREMIUM_OUTCOME_SAMPLE")
    if calibration.get("calibration_ready") is True:
        # Not a blocker by itself; a distinct explicit warning.
        sample_gate = "SAMPLE_SIZE_ONLY_NOT_EDGE"
    else:
        sample_gate = "INSUFFICIENT_MATURE_RESEARCH_SAMPLE"

    # Diagnostics: a generic source-network counter can include official
    # events, historical/indicative options, or a stale provider success.
    # It is not an independent licence/quote quality certification.
    claimed_active_option_sources = _count(network_summary.get("active_option_sources"))
    no_approved_chain = (_count(coverage.get("option_live_primary_chains_reported")) or 0) == 0
    reporting_disagreements: list[str] = []
    if claimed_active_option_sources and no_approved_chain:
        reporting_disagreements.append("SOURCE_COUNT_NOT_PROOF_OF_APPROVED_OPTION_CHAIN")
    if (_count(summary.get("option_candidates")) or 0) > 0 and not option_qualified:
        reporting_disagreements.append("OPTION_RESEARCH_ROWS_NOT_EXECUTION_READY")

    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "based_on_report_at": generated.isoformat() if generated else None,
        "report_age_minutes_at_verification": round(age, 1) if age is not None else None,
        "source_timestamp_consistent": not mismatched,
        "report_fresh_at_verification": reports_fresh,
        "status": "NOT_TRADE_READY" if blockers else "SOURCE_GATES_SATISFIED_RESEARCH_ONLY",
        "data_ready_for_stock_analysis": bool(reports_fresh and stock_verified),
        "option_execution_quotes_verified": bool(reports_fresh and option_qualified),
        "historical_research": {
            "path_evaluated": evaluated, "target_first": success,
            "stop_first": stop, "ambiguous": ambiguous,
            "unclassified_within_evaluated": (
                evaluated - success - stop - ambiguous if history_valid else None),
            "target_first_pct_of_path_evaluated": (
                _rate(success, evaluated) if history_valid else None),
            "option_contract_basis": option_basis,
            "underlying_proxy_basis": proxy_basis,
            "outcome_counters_valid": history_valid,
            "return_or_profit_factor_verified": False,
            "sample_gate": sample_gate,
            "calibration_sample_ready": calibration.get("calibration_ready") is True,
            "win_probability_calibrated": False,
            "option_fill_outcomes_verified": False,
        },
        "source_reporting_disagreements": reporting_disagreements,
        "blockers": blockers,
        "trade_recommendations_authorized": False,
        "automated_execution_allowed": False,
        "prediction_accuracy_pct": None,
        "scope_ar": (
            "حجم العينة لا يثبت الربحية. النتائج المشتقة من حركة السهم ليست "
            "عائد عقد أوبشن منفذًا. التحديث الحديث لا يعني Quote لحظيًا. "
            "عدد مزودي البيانات البحثيين لا يثبت ترخيص عرض أو تنفيذ الأوامر."
        ),
    }
