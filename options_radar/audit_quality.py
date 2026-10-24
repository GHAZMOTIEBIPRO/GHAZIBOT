"""Pandera validation of research observations; never repairs or promotes data."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd

STATUSES = {"success", "failed", "ambiguous", "non_decisive", "pending", "unavailable", "invalid_session"}


def valid_time(value: object, now: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and stamp <= now
    except (ValueError, TypeError):
        return False


def validate_audit(audit: dict, *, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    result = {"validator": "Pandera", "status": "INVALID", "records": 0, "failure_count": 0,
              "decision_authority": False, "reason": "invalid_audit_envelope"}
    records = audit.get("records")
    if (audit.get("decision_authority") is not False
            or audit.get("mode") != "HISTORICAL_5M_OUTCOME_AUDIT"
            or not isinstance(records, dict)):
        return result
    result["records"] = len(records)
    if not records:
        return {**result, "status": "EMPTY", "reason": "no_observations"}
    try:
        import pandera.pandas as pa
    except ImportError:
        return {**result, "status": "UNAVAILABLE", "reason": "pandera_not_installed"}
    rows = []
    for key, row in records.items():
        if not isinstance(row, dict):
            return {**result, "failure_count": 1, "reason": "malformed_record"}
        point = (row.get("checkpoints") or {}).get("60m", {}) if isinstance(row.get("checkpoints"), dict) else {}
        value = point.get("directional_return_pct") if isinstance(point, dict) else None
        numeric = isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
        price = row.get("entry_price")
        price_valid = isinstance(price, (int, float)) and not isinstance(price, bool) and math.isfinite(price) and price > 0
        rows.append({"id": row.get("signal_id"), "key_matches": key == row.get("signal_id"),
                     "symbol": row.get("symbol"), "time_valid": valid_time(row.get("signal_time"), current),
                     "status": row.get("audit_status"), "research_only": row.get("decision_authority") is False,
                     "return_valid": value is None or numeric, "price_valid": price_valid})
    schema = pa.DataFrameSchema({
        "id": pa.Column(str, pa.Check.str_length(min_value=1), unique=True),
        "symbol": pa.Column(str, pa.Check.str_matches(r"^[A-Z][A-Z0-9.\-]{0,14}$")),
        "status": pa.Column(str, pa.Check.isin(STATUSES)),
        **{name: pa.Column(bool, pa.Check.eq(True)) for name in
           ("key_matches", "time_valid", "research_only", "return_valid", "price_valid")},
    }, strict=True, coerce=False)
    try:
        schema.validate(pd.DataFrame(rows), lazy=True)
    except pa.errors.SchemaErrors as exc:
        # Publish counts, never arbitrary failure values/market observations.
        return {**result, "failure_count": len(exc.failure_cases), "reason": "schema_checks_failed"}
    return {**result, "status": "VALID", "reason": "observation_schema_valid"}
