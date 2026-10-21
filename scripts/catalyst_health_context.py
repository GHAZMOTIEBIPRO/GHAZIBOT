"""Read a *published* market-operations report for Telegram editorial context.

Never fetch prices, publish raw quotes, infer a trade or promote option V11.
Provider report-generation time is not the market's source quote time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

STATE_LABELS = {
    "healthy": "سليم بحسب الفحص",
    "degraded": "تدهور جزئي",
    "critical": "حالة حرجة",
    "unavailable": "غير متاح",
}
BLOCKERS = {
    "NO_VERIFIED_OPTION_PROVIDER_FAMILY": "لا يوجد مزود خيارات مُتحقق منه",
    "NO_INDEPENDENT_CROSS_SOURCE_CHAIN": "لا يوجد تحقق مستقل من مصدرين",
    "NO_EXECUTION_GRADE_OPTION_QUOTE": "لا يوجد عرض سعر عقد صالح للتنفيذ",
    "NO_VERIFIED_OPTION_TRADE_FLOW": "لا يوجد تدفق تداول عقود حي مؤهل",
}


def _parse_utc(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def health_context(report: Any, *, now: datetime,
                   max_age_minutes: int = 120) -> dict[str, Any]:
    """Fail closed when missing, future, stale or structurally malformed."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(report, dict):
        return {"available": False, "reason": "NO_HEALTH_REPORT"}
    source_time = _parse_utc(report.get("generated_at"))
    now_utc = now.astimezone(timezone.utc)
    if source_time is None or not timedelta(0) <= now_utc - source_time <= timedelta(
        minutes=max_age_minutes
    ):
        return {"available": False, "reason": "STALE_OR_UNDATED_HEALTH"}
    status = str(report.get("status") or "").lower()
    coverage = report.get("coverage_diagnostics")
    if status not in STATE_LABELS or not isinstance(coverage, dict):
        return {"available": False, "reason": "INVALID_HEALTH_SCHEMA"}
    ready = (coverage.get("options_execution_quote_ready") is True and
             coverage.get("options_trade_flow_ready") is True)
    blocking = coverage.get("blocking_codes")
    blocks = [BLOCKERS[item] for item in blocking
              if isinstance(item, str) and item in BLOCKERS][:3] if isinstance(
                  blocking, list
              ) else []
    sec = report.get("source_status", {}).get("sec_fulltext") if isinstance(
        report.get("source_status"), dict
    ) else None
    if not isinstance(sec, dict):
        sec = {}
    sec_stamp = _parse_utc(sec.get("checked_at"))
    sec_valid = (sec_stamp is not None and
                 timedelta(0) <= now_utc - sec_stamp <= timedelta(
                     minutes=max_age_minutes
                 ))
    sec_ok = sec_valid and sec.get("available") is True
    return {
        "available": True,
        "source_time": source_time.isoformat(),
        "market_status": status,
        "status_ar": STATE_LABELS[status],
        "options_grade": "REPORTED_READY_NEEDS_V11" if ready else "NOT_VERIFIED",
        "options_ar": "مزود البيانات أبلغ عن جاهزية أولية؛ كل عقد يحتاج بوابة V11" if ready
                      else "لا توجد أهلية عقود تنفيذية مثبتة",
        "blockers": blocks,
        "sec_ar": "فحص SEC Full-Text متاح" if sec_ok
                  else "SEC Full-Text غير مثبت التوفر بهذا الفحص",
        "decision_authority": False,
    }
