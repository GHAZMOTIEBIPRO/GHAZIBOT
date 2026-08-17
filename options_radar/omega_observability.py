from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provider_readiness import assess_provider_readiness


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _generated_age_minutes(payload: dict[str, Any]) -> float | None:
    value = str(payload.get("generated_at") or "")
    if not value:
        return None
    try:
        generated = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 60.0)


def _is_stale_row(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("data_status", "freshness_label", "quote_status", "greeks_status")
    )
    if "stale" in text:
        return True
    age = row.get("last_trade_age_minutes")
    if age is not None and _number(age, 0) > 30:
        return True
    return False


def build_data_status(payload: dict[str, Any]) -> dict[str, Any]:
    stocks = [row for row in payload.get("stocks", []) if isinstance(row, dict)]
    options = [row for row in payload.get("options", []) if isinstance(row, dict)]
    catalysts = [row for row in payload.get("catalysts", []) if isinstance(row, dict)]
    expiry_rows = (
        payload.get("expiry_radar", {}).get("contracts", [])
        if isinstance(payload.get("expiry_radar"), dict)
        else []
    )
    expiry_rows = [row for row in expiry_rows if isinstance(row, dict)]
    source_network = payload.get("source_network") if isinstance(payload.get("source_network"), dict) else {}
    source_summary = source_network.get("summary", {}) if isinstance(source_network, dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    catalyst_intelligence = omega.get("catalyst_intelligence", {}) if isinstance(omega, dict) else {}
    sec_metrics = payload.get("sec_incremental_metrics") if isinstance(payload.get("sec_incremental_metrics"), dict) else {}
    provider_audit = payload.get("provider_audit") if isinstance(payload.get("provider_audit"), dict) else {}
    provider_readiness = (
        assess_provider_readiness(provider_audit).as_dict()
        if provider_audit
        else None
    )

    stale_count = sum(_is_stale_row(row) for row in options)
    missing_expiry_family = sum(
        not str(row.get("expiry_family") or "").strip()
        or str(row.get("expiry_family") or "").upper() == "UNKNOWN"
        for row in expiry_rows
    )
    generated_age = _generated_age_minutes(payload)
    critical_errors = [
        key for key in errors
        if any(token in str(key).lower() for token in ("options", "stocks", "catalyst", "export"))
    ]

    run_duration = None
    performance = payload.get("performance")
    if isinstance(performance, dict):
        for key in ("total_run_seconds", "run_duration_seconds", "elapsed_seconds", "total_seconds"):
            if key in performance:
                run_duration = _number(performance.get(key))
                break

    status = "healthy"
    reasons: list[str] = []
    if critical_errors:
        status = "degraded"
        reasons.append(f"{len(critical_errors)} critical pipeline error(s)")
    if stale_count:
        status = "degraded"
        reasons.append(f"{stale_count} stale option row(s)")
    if generated_age is not None and generated_age > 180:
        status = "stale"
        reasons.append(f"published dataset age {generated_age:.0f} minutes")
    if missing_expiry_family:
        status = "degraded" if status == "healthy" else status
        reasons.append(f"{missing_expiry_family} expiry row(s) missing family")
    if provider_readiness:
        readiness_status = str(provider_readiness.get("status") or "UNKNOWN")
        if readiness_status.startswith("CRITICAL"):
            status = "degraded" if status == "healthy" else status
        elif not bool(provider_readiness.get("production_quote_ready")) or not bool(
            provider_readiness.get("production_flow_ready")
        ):
            status = "degraded" if status == "healthy" else status
        reasons.extend(
            str(value)
            for value in provider_readiness.get("reasons", [])
            if str(value).strip()
        )

    return {
        "status": status,
        "generated_at": payload.get("generated_at"),
        "dataset_age_minutes": round(generated_age, 1) if generated_age is not None else None,
        "last_successful_refresh": payload.get("generated_at") if not critical_errors else None,
        "option_provider": payload.get("options_provider"),
        "option_provider_readiness": provider_readiness,
        "source_status": {
            "active_stock_sources": source_summary.get("active_stock_sources", 0),
            "active_option_sources": source_summary.get("active_option_sources", 0),
            "option_provider_readiness": (
                provider_readiness.get("status") if provider_readiness else None
            ),
            "production_option_quotes": (
                provider_readiness.get("production_quote_ready") if provider_readiness else None
            ),
            "production_option_flow": (
                provider_readiness.get("production_flow_ready") if provider_readiness else None
            ),
            "sec_fulltext": (
                payload.get("operational_status", {}).get("sec_fulltext_status")
                if isinstance(payload.get("operational_status"), dict)
                else None
            ),
        },
        "row_counts": {
            "stocks": len(stocks),
            "options": len(options),
            "catalysts": len(catalysts),
            "expiry_contracts": len(expiry_rows),
        },
        "quality_counts": {
            "stale_options": stale_count,
            "missing_expiry_family": missing_expiry_family,
            "duplicate_events_collapsed": catalyst_intelligence.get("duplicates_collapsed", 0),
            "errors": len(errors),
            "critical_errors": len(critical_errors),
            "fallback_only_option_chains": (
                provider_readiness.get("fallback_only_chains", 0) if provider_readiness else 0
            ),
            "live_primary_option_chains": (
                provider_readiness.get("live_primary_chains", 0) if provider_readiness else 0
            ),
        },
        "sec_incremental": sec_metrics,
        "run_duration_seconds": run_duration,
        "reasons": list(dict.fromkeys(reasons)),
    }


def build_health(payload: dict[str, Any]) -> dict[str, Any]:
    data_status = build_data_status(payload)
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    validation = omega.get("validation") if isinstance(omega, dict) else {}
    readiness = data_status.get("option_provider_readiness") or {}
    critical_error_count = int(data_status["quality_counts"]["critical_errors"])
    critical_pipeline_ok = critical_error_count == 0
    return {
        "service": "GHAZIBOT",
        "status": data_status["status"],
        "generated_at": payload.get("generated_at"),
        "schema_version": payload.get("schema_version"),
        "health_schema_version": 2,
        "model_version": payload.get("model_version"),
        "research_status": validation.get("edge_status", "EDGE NOT YET PROVEN"),
        "checks": {
            "dataset_fresh": (
                data_status["dataset_age_minutes"] is None
                or data_status["dataset_age_minutes"] <= 180
            ),
            "critical_pipeline_ok": critical_pipeline_ok,
            "critical_pipeline_error_count": critical_error_count,
            "critical_pipeline_errors": critical_pipeline_ok,
            "expiry_identity_complete": data_status["quality_counts"]["missing_expiry_family"] == 0,
            "option_quotes_production_ready": readiness.get("production_quote_ready") if readiness else None,
            "option_flow_production_ready": readiness.get("production_flow_ready") if readiness else None,
        },
        "check_contract": {
            "critical_pipeline_ok": "true means zero critical stock/options/catalyst/export pipeline errors",
            "critical_pipeline_error_count": "integer count of critical pipeline errors",
            "critical_pipeline_errors": "deprecated compatibility alias; true also means zero critical errors",
        },
    }


def apply_observability(payload: dict[str, Any]) -> None:
    payload["data_status"] = build_data_status(payload)
    payload["health"] = build_health(payload)


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_status_files(output_path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(output_path)
    apply_observability(payload)
    _write_atomic(output.parent / "health.json", payload["health"])
    _write_atomic(output.parent / "data-status.json", payload["data_status"])
