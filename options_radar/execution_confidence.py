from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

_DELAYED_TOKENS = (
    "delayed",
    "indicative",
    "sandbox",
    "unofficial",
    "may be delayed",
    "yahoo",
    "yfinance",
    "24h",
    "research",
)
_TRUSTED_LIVE_TOKENS = (
    "opra",
    "alpaca_opra_stream",
    "intrinio-opra",
    "databento",
    "massive",
    "polygon_options",
    "polygon options",
    "tradier",
    "brokerage feed",
)
_ACCOUNT_TOKENS = (
    "account entitlement",
    "account feed",
    "broker account",
    "brokerage account",
)
_TIMESTAMP_KEYS = (
    "quote_timestamp",
    "quote_time",
    "quote_at",
    "updated_at",
    "data_timestamp",
    "snapshot_at",
    "as_of",
    "last_updated",
    "event_at",
    "timestamp",
    "generated_at",
)


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_text(row: dict[str, Any]) -> str:
    return " ".join(
        _text(row.get(key)).lower()
        for key in (
            "source",
            "provider",
            "freshness_label",
            "fabric_source_tier",
            "fabric_quote_provider",
            "stream_feed",
            "data_mode",
            "data_quality_label",
        )
        if row.get(key) is not None
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None

    numeric = _number(value)
    if numeric is not None and not isinstance(value, str):
        raw = numeric
        if raw > 1e16:
            raw /= 1e9
        elif raw > 1e11:
            raw /= 1e3
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    text = _text(value)
    if not text:
        return None
    try:
        raw = float(text)
    except ValueError:
        raw = None
    if raw is not None and math.isfinite(raw):
        if raw > 1e16:
            raw /= 1e9
        elif raw > 1e11:
            raw /= 1e3
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        stamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _quote_timestamp(row: dict[str, Any]) -> tuple[datetime | None, str]:
    for key in _TIMESTAMP_KEYS:
        stamp = _parse_timestamp(row.get(key))
        if stamp is not None:
            return stamp, key
    return None, ""


@dataclass(frozen=True)
class ExecutionGate:
    confidence: str
    execution_ready: bool
    quote_timestamp: str
    quote_age_seconds: float | None
    source_mode: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


def assess_execution_quote(
    row: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_quote_age_seconds: float = 120.0,
    max_clock_skew_seconds: float = 5.0,
) -> ExecutionGate:
    """Fail-closed per-contract execution gate.

    Source labels and precomputed relative ages are insufficient. A contract must
    carry an absolute quote timestamp, a trusted live/account source and a valid
    two-sided quote before it may be execution-ready.
    """
    record = row if isinstance(row, dict) else {}
    source_text = _source_text(record)
    blockers: list[str] = []

    delayed = any(token in source_text for token in _DELAYED_TOKENS)
    trusted_live = any(token in source_text for token in _TRUSTED_LIVE_TOKENS)
    account = any(token in source_text for token in _ACCOUNT_TOKENS)

    if delayed:
        source_mode = "DELAYED_OR_RESEARCH"
        base_confidence = "RESEARCH"
        blockers.append("مصدر العقد مؤجل/بحثي أو يحمل علامة تمنع التنفيذ")
    elif account:
        source_mode = "ACCOUNT"
        base_confidence = "ACCOUNT"
    elif trusted_live:
        source_mode = "LIVE"
        base_confidence = "LIVE"
    elif source_text:
        source_mode = "UNVERIFIED"
        base_confidence = "RESEARCH"
        blockers.append("المصدر لا يثبت تغذية خيارات حية ومرخّصة")
    else:
        source_mode = "UNAVAILABLE"
        base_confidence = "UNAVAILABLE"
        blockers.append("مصدر بيانات العقد غير معروف")

    bid = _number(record.get("bid"), 0.0) or 0.0
    ask = _number(record.get("ask"), 0.0) or 0.0
    if bid <= 0 or ask <= 0 or ask < bid:
        blockers.append("لا يوجد Bid/Ask صالح ثنائي الجانب")

    stamp, stamp_key = _quote_timestamp(record)
    quote_age: float | None = None
    quote_timestamp = ""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if stamp is not None:
        quote_timestamp = stamp.isoformat()
        quote_age = (current - stamp).total_seconds()

    if quote_age is None:
        blockers.append("لا يوجد توقيت Quote مطلق يمكن التحقق من حداثته")
    elif quote_age < -abs(max_clock_skew_seconds):
        blockers.append("توقيت Quote يقع في المستقبل خارج سماحية الساعة")
    elif quote_age > max(1.0, float(max_quote_age_seconds)):
        blockers.append(
            f"Quote قديم ({quote_age:.0f}ث) ويتجاوز الحد {float(max_quote_age_seconds):.0f}ث"
        )

    ready = (
        base_confidence in {"LIVE", "ACCOUNT"}
        and not delayed
        and bid > 0
        and ask >= bid
        and quote_age is not None
        and quote_age >= -abs(max_clock_skew_seconds)
        and quote_age <= max(1.0, float(max_quote_age_seconds))
        and not blockers
    )

    confidence = base_confidence if ready else (
        "UNAVAILABLE" if base_confidence == "UNAVAILABLE" else "RESEARCH"
    )
    if ready:
        blockers = []

    return ExecutionGate(
        confidence=confidence,
        execution_ready=ready,
        quote_timestamp=quote_timestamp,
        quote_age_seconds=round(quote_age, 3) if quote_age is not None else None,
        source_mode=source_mode if not stamp_key else f"{source_mode}:{stamp_key}",
        blockers=tuple(dict.fromkeys(blockers)),
    )
