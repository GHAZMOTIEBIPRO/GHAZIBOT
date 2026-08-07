from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

    return {
        "status": status,
        "generated_at": payload.get("generated_at"),
        "dataset_age_minutes": round(generated_age, 1) if generated_age is not None else None,
        "last_successful_refresh": payload.get("generated_at") if not critical_errors else None,
        "option_provider": payload.get("options_provider"),
        "source_status": {
            "active_stock_sources": source_summary.get("active_stock_sources", 0),
            "active_option_sources": source_summary.get("active_option_sources", 0),
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
        },
        "sec_incremental": sec_metrics,
        "run_duration_seconds": run_duration,
        "reasons": reasons,
    }


def build_health(payload: dict[str, Any]) -> dict[str, Any]:
    data_status = build_data_status(payload)
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    validation = omega.get("validation") if isinstance(omega, dict) else {}
    return {
        "service": "GHAZIBOT",
        "status": data_status["status"],
        "generated_at": payload.get("generated_at"),
        "schema_version": payload.get("schema_version"),
        "model_version": payload.get("model_version"),
        "research_status": validation.get("edge_status", "EDGE NOT YET PROVEN"),
        "checks": {
            "dataset_fresh": (
                data_status["dataset_age_minutes"] is None
                or data_status["dataset_age_minutes"] <= 180
            ),
            "critical_pipeline_errors": data_status["quality_counts"]["critical_errors"] == 0,
            "expiry_identity_complete": data_status["quality_counts"]["missing_expiry_family"] == 0,
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
