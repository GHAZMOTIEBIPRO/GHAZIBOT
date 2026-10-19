"""Cross-check completed daily closes between licensed, independent vendors.

A family counts only when its API key is configured AND the owner attested
(repository variable) that the account terms permit internal non-display
analysis. Yahoo transports are never a licensed family. Output carries
agreement statistics only; no price is published.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
# family -> (credential env vars, owner attestation variable)
LICENSED_FAMILIES: dict[str, tuple[tuple[str, ...], str]] = {
    "tiingo": (("TIINGO_API_KEY",), "TIINGO_NON_DISPLAY_USE_AUTHORIZED"),
    "alpaca": (("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), "ALPACA_INTERNAL_DATA_USE_AUTHORIZED"),
    "twelve_data": (("TWELVE_DATA_API_KEY",), "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED"),
    "polygon": (("POLYGON_API_KEY",), "POLYGON_NON_DISPLAY_USE_AUTHORIZED"),
    "alpha_vantage": (("ALPHA_VANTAGE_API_KEY",), "ALPHA_VANTAGE_NON_DISPLAY_USE_AUTHORIZED"),
}
CHECK_SYMBOLS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "SPY", "QQQ")
TOLERANCE_BPS = 25.0
MIN_SYMBOLS = 5
MIN_AGREEMENT = 0.8


def eligible_families(env: Mapping[str, str]) -> list[str]:
    return [family for family, (keys, attestation) in LICENSED_FAMILIES.items()
            if all(str(env.get(key) or "").strip() for key in keys)
            and str(env.get(attestation) or "").strip().lower() == "true"]


def _close_map(frame: Any) -> dict[date, float]:
    """Daily closes keyed by NY session date from a normalised bar frame."""
    out: dict[date, float] = {}
    if frame is None or getattr(frame, "empty", True) or "Close" not in frame:
        return out
    for stamp, close in frame["Close"].items():
        try:
            value = float(close)
            day = stamp.tz_convert(NY).date() if getattr(stamp, "tzinfo", None) else stamp.date()
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(value) and value > 0:
            out[day] = value
    return out


def compare_symbol(closes: dict[str, dict[date, float]], *, before: date) -> dict[str, Any] | None:
    """Latest completed session (< ``before``) that every family reports."""
    families = [f for f, series in closes.items() if series]
    if len(families) < 2:
        return None
    common = set.intersection(*(set(closes[f]) for f in families))
    sessions = sorted(day for day in common if day < before)
    if not sessions:
        return None
    day = sessions[-1]
    values = {f: closes[f][day] for f in families}
    # Full spread between vendors (not distance to a median, which halves a
    # two-vendor gap).
    spread = (max(values.values()) - min(values.values())) / median(values.values()) * 10_000
    agree = spread <= TOLERANCE_BPS
    return {
        "session": day.isoformat(),
        "families": sorted(families),
        "max_divergence_bps": round(spread, 2),
        "agree": agree,
        "agreeing_families": sorted(families) if agree else [],
    }


def run_check(fetch: Callable[[str, str], Any], families: list[str], *, now: datetime,
              symbols: tuple[str, ...] = CHECK_SYMBOLS) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.astimezone(NY).date()
    rows, errors = {}, {}
    for symbol in symbols:
        closes: dict[str, dict[date, float]] = {}
        for family in families:
            try:
                closes[family] = _close_map(fetch(family, symbol))
            except Exception as exc:  # noqa: BLE001 - never echo vendor text (may carry tokens)
                errors[f"{symbol}:{family}"] = type(exc).__name__
        result = compare_symbol(closes, before=today)
        if result:
            rows[symbol] = result
    compared = len(rows)
    agreed = sum(row["agree"] for row in rows.values())
    ratio = agreed / compared if compared else None
    confirming = sorted({f for row in rows.values() if row["agree"] for f in row["agreeing_families"]})
    verified = (len(families) >= 2 and compared >= MIN_SYMBOLS
                and ratio is not None and ratio >= MIN_AGREEMENT and len(confirming) >= 2)
    bps = [row["max_divergence_bps"] for row in rows.values()]
    return {
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "status": ("VERIFIED_LICENSED" if verified else
                   "INSUFFICIENT_LICENSED_SOURCES" if len(families) < 2 else "NOT_VERIFIED"),
        "licensed_families": families,
        "confirming_families": confirming if verified else [],
        "symbols_compared": compared,
        "symbols_agreeing": agreed,
        "concordance_ratio": round(ratio, 4) if ratio is not None else None,
        "median_max_divergence_bps": round(median(bps), 2) if bps else None,
        "tolerance_bps": TOLERANCE_BPS,
        "sessions_compared": sorted({row["session"] for row in rows.values()}),
        "errors": errors,
        "price_data_published": False,
    }
