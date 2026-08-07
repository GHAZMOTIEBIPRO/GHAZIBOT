from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

EXPIRY_FAMILIES = {
    "DAILY",
    "WEEKLY",
    "STANDARD_MONTHLY",
    "END_OF_MONTH",
    "QUARTERLY",
    "LEAPS",
    "SPECIAL",
    "UNKNOWN",
}

_PROVIDER_FAMILY_KEYS = (
    "provider_expiry_family",
    "expiry_family",
    "expiration_type",
    "expiry_type",
    "series_type",
    "series",
    "expiration_kind",
    "contract_type",
)

_OCC_SYMBOL = re.compile(r"^(?P<root>[A-Z]{1,8})\d{6}[CP]\d{8}$")


@dataclass(frozen=True)
class ExpiryIdentity:
    expiration_date: str
    calendar_dte: int
    trading_dte: int
    dte_bucket: str
    expiry_family: str
    is_standard_monthly: bool
    is_weekly: bool
    is_daily: bool
    is_quarterly: bool
    is_end_of_month: bool
    is_leaps: bool
    root_symbol: str
    option_root: str
    settlement_type: str
    settlement_time: str
    exercise_style: str
    multiplier: int
    expiry_source: str
    classification_confidence: float
    classification_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _safe_date(value: Any) -> date | None:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return stamp.date()


def _as_of_date(value: date | datetime | pd.Timestamp | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, pd.Timestamp):
        stamp = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
        return stamp.date()
    return value


def holding_horizon_bucket(dte: int | float | str | None) -> str:
    try:
        days = int(float(dte))
    except (TypeError, ValueError, OverflowError):
        return "UNKNOWN_DTE"
    if days < 0:
        return "EXPIRED"
    if days == 0:
        return "0DTE"
    if days <= 2:
        return "1-2_DTE"
    if days <= 7:
        return "3-7_DTE"
    if days <= 14:
        return "8-14_DTE"
    if days <= 30:
        return "15-30_DTE"
    if days <= 60:
        return "31-60_DTE"
    return "60+_DTE"


def _normalise_provider_family(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    aliases = {
        "DAILY": "DAILY",
        "DAY": "DAILY",
        "0DTE": "DAILY",
        "WEEKLY": "WEEKLY",
        "WEEK": "WEEKLY",
        "WEEKLIES": "WEEKLY",
        "STANDARD_MONTHLY": "STANDARD_MONTHLY",
        "STANDARD": "STANDARD_MONTHLY",
        "MONTHLY": "STANDARD_MONTHLY",
        "MONTH": "STANDARD_MONTHLY",
        "REGULAR": "STANDARD_MONTHLY",
        "EOM": "END_OF_MONTH",
        "END_OF_MONTH": "END_OF_MONTH",
        "MONTH_END": "END_OF_MONTH",
        "QUARTERLY": "QUARTERLY",
        "QUARTER": "QUARTERLY",
        "LEAPS": "LEAPS",
        "LEAP": "LEAPS",
        "LONG_TERM": "LEAPS",
        "SPECIAL": "SPECIAL",
        "FLEX": "SPECIAL",
        "UNKNOWN": "UNKNOWN",
    }
    if text in aliases:
        return aliases[text]
    for needle, family in (
        ("WEEK", "WEEKLY"),
        ("MONTHLY", "STANDARD_MONTHLY"),
        ("END_OF_MONTH", "END_OF_MONTH"),
        ("QUART", "QUARTERLY"),
        ("LEAP", "LEAPS"),
        ("DAILY", "DAILY"),
        ("SPECIAL", "SPECIAL"),
    ):
        if needle in text:
            return family
    return None


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    first_friday = 1 + ((4 - first.weekday()) % 7)
    return date(year, month, first_friday + 14)


def _last_weekday_of_month(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    candidate = next_month - pd.Timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= pd.Timedelta(days=1)
    return candidate.date() if isinstance(candidate, pd.Timestamp) else candidate


def _is_last_weekday(expiration: date) -> bool:
    return expiration == _last_weekday_of_month(expiration.year, expiration.month)


def _is_holiday_shifted_friday(expiration: date) -> tuple[bool, bool]:
    if expiration.weekday() != 3:
        return False, False
    following = expiration + pd.Timedelta(days=1)
    following_date = following.date() if isinstance(following, pd.Timestamp) else following
    is_friday = following_date.weekday() == 4
    is_standard = following_date == _third_friday(following_date.year, following_date.month)
    return is_friday, is_standard


def _root_from_contract(contract_symbol: Any) -> str:
    text = _clean_text(contract_symbol).replace("O:", "").replace("_", "")
    match = _OCC_SYMBOL.fullmatch(text)
    return match.group("root") if match else ""


def _explicit_root(row: dict[str, Any]) -> tuple[str, str]:
    symbol = _clean_text(row.get("symbol"))
    root = _clean_text(row.get("root_symbol") or row.get("root") or symbol)
    option_root = _clean_text(row.get("option_root") or row.get("root_symbol"))
    parsed_root = _root_from_contract(row.get("contract_symbol"))
    if not option_root:
        option_root = parsed_root or root
    if not root:
        root = parsed_root or symbol
    return root, option_root


def _provider_family(row: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in _PROVIDER_FAMILY_KEYS:
        family = _normalise_provider_family(row.get(key))
        if family:
            return family, key
    return None, None


def _product_defaults(root: str, option_root: str) -> tuple[str, str, str, int]:
    effective = option_root or root
    if effective == "SPX":
        return "CASH", "AM", "EUROPEAN", 100
    if effective == "SPXW":
        return "CASH", "PM", "EUROPEAN", 100
    if effective in {"NDX", "XND"}:
        return "CASH", "UNKNOWN", "EUROPEAN", 100
    return "PHYSICAL", "PM", "AMERICAN", 100


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed > 0 else default


def _field_or_default(row: dict[str, Any], keys: tuple[str, ...], default: str) -> str:
    for key in keys:
        text = _clean_text(row.get(key))
        if text:
            return text
    return default


def _calendar_fallback_family(
    expiration: date,
    *,
    calendar_dte: int,
    root: str,
    option_root: str,
) -> tuple[str, float, str]:
    effective = option_root or root
    if calendar_dte >= 365:
        return "LEAPS", 0.55, "calendar_fallback_leaps"

    if effective == "SPX":
        if expiration == _third_friday(expiration.year, expiration.month):
            return "STANDARD_MONTHLY", 0.92, "product_rule_spx_standard"
        shifted, shifted_standard = _is_holiday_shifted_friday(expiration)
        if shifted and shifted_standard:
            return "STANDARD_MONTHLY", 0.72, "calendar_holiday_shift_fallback"
        return "UNKNOWN", 0.35, "calendar_fallback_unknown"

    if effective == "SPXW":
        if _is_last_weekday(expiration) and expiration.month not in {3, 6, 9, 12}:
            return "END_OF_MONTH", 0.82, "product_rule_spxw_eom"
        return "WEEKLY", 0.88, "product_rule_spxw_weekly"

    if expiration == _third_friday(expiration.year, expiration.month):
        return "STANDARD_MONTHLY", 0.68, "calendar_fallback"

    shifted, shifted_standard = _is_holiday_shifted_friday(expiration)
    if shifted:
        if shifted_standard:
            return "STANDARD_MONTHLY", 0.58, "calendar_holiday_shift_fallback"
        return "WEEKLY", 0.52, "calendar_holiday_shift_fallback"

    if expiration.weekday() == 4:
        return "WEEKLY", 0.58, "calendar_fallback"

    if _is_last_weekday(expiration) and expiration.month not in {3, 6, 9, 12}:
        if effective in {"SPY", "QQQ", "IWM", "NDX", "XND"}:
            return "END_OF_MONTH", 0.45, "calendar_fallback_eom"

    return "UNKNOWN", 0.30, "calendar_fallback_unknown"


def classify_expiry(
    row: dict[str, Any],
    *,
    as_of: date | datetime | pd.Timestamp | None = None,
) -> ExpiryIdentity:
    expiration = _safe_date(row.get("expiration") or row.get("expiration_date"))
    if expiration is None:
        expiration = date(1970, 1, 1)
        expiration_valid = False
    else:
        expiration_valid = True

    today = _as_of_date(as_of)
    calendar_dte = (expiration - today).days if expiration_valid else -1
    if expiration_valid:
        trading_dte = int(np.busday_count(today.isoformat(), expiration.isoformat()))
    else:
        trading_dte = -1

    root, option_root = _explicit_root(row)
    provider_family, provider_key = _provider_family(row)
    if provider_family is not None:
        family = provider_family
        confidence = 0.99
        method = f"provider_metadata:{provider_key}"
    elif not expiration_valid:
        family = "UNKNOWN"
        confidence = 0.0
        method = "missing_expiration"
    else:
        family, confidence, method = _calendar_fallback_family(
            expiration,
            calendar_dte=calendar_dte,
            root=root,
            option_root=option_root,
        )

    if family not in EXPIRY_FAMILIES:
        family = "UNKNOWN"
        confidence = 0.0
        method = "invalid_family_guard"

    default_settlement, default_time, default_exercise, default_multiplier = _product_defaults(
        root,
        option_root,
    )
    settlement_type = _field_or_default(
        row,
        ("settlement_type", "settlement", "settlement_style"),
        default_settlement,
    )
    settlement_time = _field_or_default(
        row,
        ("settlement_time", "settlement_session"),
        default_time,
    )
    exercise_style = _field_or_default(
        row,
        ("exercise_style", "exercise_type"),
        default_exercise,
    )
    multiplier = _positive_int(row.get("multiplier") or row.get("contract_size"), default_multiplier)
    source = str(row.get("source") or row.get("expiry_source") or "unknown")

    return ExpiryIdentity(
        expiration_date=expiration.isoformat() if expiration_valid else "",
        calendar_dte=calendar_dte,
        trading_dte=trading_dte,
        dte_bucket=holding_horizon_bucket(calendar_dte),
        expiry_family=family,
        is_standard_monthly=family == "STANDARD_MONTHLY",
        is_weekly=family == "WEEKLY",
        is_daily=family == "DAILY",
        is_quarterly=family == "QUARTERLY",
        is_end_of_month=family == "END_OF_MONTH",
        is_leaps=family == "LEAPS",
        root_symbol=root,
        option_root=option_root,
        settlement_type=settlement_type,
        settlement_time=settlement_time,
        exercise_style=exercise_style,
        multiplier=multiplier,
        expiry_source=source,
        classification_confidence=round(max(0.0, min(1.0, float(confidence))), 4)
        if math.isfinite(confidence)
        else 0.0,
        classification_method=method,
    )
