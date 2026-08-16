from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from options_radar.market_clock import market_clock_state

FINAL_TERMINAL = frozenset({"success", "failed", "ambiguous", "non_decisive"})
INVALID_SESSION_CLASSIFICATION = "invalid_session"
DEFAULT_RETRY_COOLDOWN_HOURS = 18


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def migrate_and_classify_records(audit: dict[str, Any]) -> dict[str, Any]:
    """Migrate old audit state and quarantine signals outside valid market activity.

    Invalid-session rows remain visible as operational evidence but are excluded
    from performance coverage. Their outcome status is `unavailable`; the reason
    is carried separately in `audit_classification` to avoid inventing a new
    market outcome category.
    """

    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    for row in records.values():
        if not isinstance(row, dict):
            continue
        if "audit_attempt_count" not in row:
            row["audit_attempt_count"] = 1 if row.get("audited_at") else 0
        if not row.get("audit_last_attempt_at") and row.get("audited_at"):
            row["audit_last_attempt_at"] = row.get("audited_at")
        row.setdefault("audit_last_attempt_result", "legacy" if row.get("audited_at") else "never_attempted")

        created = _parse_time(row.get("signal_time"))
        if created is None:
            row["signal_session_valid"] = False
            row["signal_session_reason"] = "invalid_signal_time"
            row["audit_classification"] = INVALID_SESSION_CLASSIFICATION
            row["audit_status"] = "unavailable"
            row["audit_reason"] = "invalid_signal_session:invalid_signal_time"
            continue

        clock = market_clock_state(created)
        row["signal_session_valid"] = bool(clock.is_extended_activity_open)
        row["signal_session_reason"] = clock.reason
        row["signal_session_date"] = clock.session_date
        if not clock.is_extended_activity_open:
            row["audit_classification"] = INVALID_SESSION_CLASSIFICATION
            row["audit_status"] = "unavailable"
            row["audit_reason"] = f"invalid_signal_session:{clock.reason}"
            row["decision_authority"] = False
        elif row.get("audit_classification") == INVALID_SESSION_CLASSIFICATION:
            row.pop("audit_classification", None)
    audit["records"] = records
    return audit


def _needs_more_evidence(row: dict[str, Any]) -> bool:
    if row.get("signal_session_valid") is False:
        return False
    status = str(row.get("audit_status") or "pending")
    return status not in FINAL_TERMINAL


def fair_symbols_needing_backfill(
    audit: dict[str, Any],
    *,
    now: datetime,
    maximum_symbols: int,
    retry_cooldown_hours: int = DEFAULT_RETRY_COOLDOWN_HOURS,
) -> list[str]:
    """Prefer never-attempted symbols, then cooled-down retries.

    Terminal decisive/ambiguous/non-decisive events leave the queue immediately;
    a missing 1d checkpoint cannot make a resolved event monopolize future slots.
    """

    current = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    cooldown = timedelta(hours=max(1, int(retry_cooldown_hours)))
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    candidates: dict[str, tuple[int, datetime, int]] = {}

    for row in records.values():
        if not isinstance(row, dict) or not _needs_more_evidence(row):
            continue
        created = _parse_time(row.get("signal_time"))
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol or created is None or current < created + timedelta(minutes=15):
            continue

        attempts = max(0, _int(row.get("audit_attempt_count")))
        last_attempt = _parse_time(row.get("audit_last_attempt_at"))
        coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}

        if attempts <= 0:
            tier = 0
        else:
            if last_attempt is not None and current - last_attempt < cooldown:
                continue
            tier = 1 if coverage.get("60m") is not True else 2

        priority = (tier, created, attempts)
        previous = candidates.get(symbol)
        if previous is None or priority < previous:
            candidates[symbol] = priority

    ordered = sorted(candidates, key=lambda symbol: (*candidates[symbol], symbol))
    return ordered[: max(1, int(maximum_symbols))]


def mark_symbol_attempt(
    audit: dict[str, Any],
    *,
    symbol: str,
    now: datetime,
    result: str,
    error: str = "",
) -> None:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    current = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    stamp = current.isoformat()
    for row in records.values():
        if not isinstance(row, dict) or str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        audited_at = _parse_time(row.get("audited_at"))
        touched_now = audited_at is not None and abs((audited_at - current).total_seconds()) <= 1
        if not _needs_more_evidence(row) and not touched_now:
            continue
        row["audit_attempt_count"] = max(0, _int(row.get("audit_attempt_count"))) + 1
        row["audit_last_attempt_at"] = stamp
        row["audit_last_attempt_result"] = str(result)
        if error:
            row["audit_last_attempt_error"] = str(error)[:500]
        else:
            row.pop("audit_last_attempt_error", None)


@dataclass(frozen=True)
class FairCoverage:
    total_records: int
    eligible_records: int
    invalid_session: int
    covered_15m: int
    covered_60m: int
    covered_1d: int
    decisive: int
    ambiguous: int
    non_decisive: int
    pending: int
    unavailable: int
    discrepancies: int
    never_attempted: int

    def as_dict(self) -> dict[str, Any]:
        denominator = max(1, self.eligible_records)
        return {
            "records": self.eligible_records,
            "records_total": self.total_records,
            "eligible_records": self.eligible_records,
            "invalid_session": self.invalid_session,
            "covered_15m": self.covered_15m,
            "covered_60m": self.covered_60m,
            "covered_1d": self.covered_1d,
            "coverage_15m_pct": round(100.0 * self.covered_15m / denominator, 2),
            "coverage_60m_pct": round(100.0 * self.covered_60m / denominator, 2),
            "coverage_1d_pct": round(100.0 * self.covered_1d / denominator, 2),
            "decisive": self.decisive,
            "ambiguous": self.ambiguous,
            "non_decisive": self.non_decisive,
            "pending": self.pending,
            "unavailable": self.unavailable,
            "snapshot_discrepancies": self.discrepancies,
            "never_attempted": self.never_attempted,
        }


def recalculate_fair_coverage(audit: dict[str, Any]) -> dict[str, Any]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    rows = [row for row in records.values() if isinstance(row, dict)]
    eligible = [row for row in rows if row.get("signal_session_valid") is not False]

    def covered(label: str) -> int:
        return sum(bool((row.get("coverage") or {}).get(label)) for row in eligible)

    coverage = FairCoverage(
        total_records=len(rows),
        eligible_records=len(eligible),
        invalid_session=len(rows) - len(eligible),
        covered_15m=covered("15m"),
        covered_60m=covered("60m"),
        covered_1d=covered("1d"),
        decisive=sum(row.get("audit_status") in {"success", "failed"} for row in eligible),
        ambiguous=sum(row.get("audit_status") == "ambiguous" for row in eligible),
        non_decisive=sum(row.get("audit_status") == "non_decisive" for row in eligible),
        pending=sum(row.get("audit_status") == "pending" for row in eligible),
        unavailable=sum(row.get("audit_status") == "unavailable" for row in eligible),
        discrepancies=sum(row.get("snapshot_discrepancy") is True for row in eligible),
        never_attempted=sum(_int(row.get("audit_attempt_count")) <= 0 for row in eligible),
    )
    audit["coverage"] = coverage.as_dict()
    audit["invalid_session_policy"] = {
        "classification": INVALID_SESSION_CLASSIFICATION,
        "tracked_as_operational_defect": True,
        "excluded_from_performance_denominator": True,
        "stored_audit_status": "unavailable",
        "deleted": False,
    }
    return audit
