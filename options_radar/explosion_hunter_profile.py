"""Research-only configuration for aggressive 100% explosion hunting.

Do not interpret the target as a probability or a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HunterProfile:
    target_return_pct: float = 100.0
    sessions_forward: int = 5
    sessions: tuple[str, ...] = ("PREMARKET", "REGULAR")
    risk: str = "AGGRESSIVE"
    minimum_rvol: float = 2.0
    maximum_float_shares: int = 10_000_000
    minimum_dollar_volume: float = 250_000.0


PROFILE = HunterProfile()


def is_verified_sec_url(value: object) -> bool:
    """Accept SEC HTTPS filing links only, not lookalike hosts or credentials."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value.strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"sec.gov", "www.sec.gov"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and parsed.path.startswith(("/Archives/", "/ixviewer/"))
        )
    except ValueError:
        return False



def classify_candidate(row: dict, *, profile: HunterProfile = PROFILE, now: datetime | None = None, max_quote_age_minutes: float = 15.0) -> dict:
    """Classify evidence; never manufacture missing float or timestamp."""
    def numeric(key: str) -> float | None:
        try:
            value = row.get(key)
            if value is None or isinstance(value, bool):
                return None
            number = float(value)
            from math import isfinite
            return number if isfinite(number) else None
        except (TypeError, ValueError):
            return None

    rvol = numeric("rvol")
    free_float = numeric("float_shares")
    dollar_volume = numeric("dollar_volume")
    move = numeric("day_move_pct")
    quote_time = row.get("provider_quote_timestamp")
    catalyst_url = row.get("official_catalyst_url")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or max_quote_age_minutes <= 0:
        raise ValueError("now must be timezone-aware and maximum quote age positive")
    quote_fresh = False
    if isinstance(quote_time, str):
        try:
            parsed = datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                age = (reference.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
                quote_fresh = -60 <= age <= max_quote_age_minutes * 60
        except ValueError:
            pass
    official_sec_evidence = is_verified_sec_url(catalyst_url)
    evidence = bool(quote_time) and official_sec_evidence
    flags = []
    if rvol is None or rvol < profile.minimum_rvol:
        flags.append("INSUFFICIENT_RVOL")
    if free_float is None:
        flags.append("FLOAT_UNVERIFIED")
    elif free_float <= 0 or free_float > profile.maximum_float_shares:
        flags.append("FLOAT_OUTSIDE_PROFILE")
    if dollar_volume is None or dollar_volume < profile.minimum_dollar_volume:
        flags.append("LIQUIDITY_UNVERIFIED")
    if not evidence:
        flags.append("CATALYST_OR_QUOTE_PROVENANCE_MISSING")
    if not official_sec_evidence:
        flags.append("SEC_CATALYST_PROVENANCE_UNVERIFIED")
    if not quote_fresh:
        flags.append("QUOTE_TIMESTAMP_STALE_OR_INVALID")
    if move is not None and move >= 35:
        flags.append("CHASE_RISK")
    stage = "WATCH" if not flags else "RESEARCH_ONLY"
    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "stage": stage,
        "flags": flags,
        "target_return_pct": profile.target_return_pct,
        "target_is_forecast": False,
        "target_is_probability": False,
        "sessions": list(profile.sessions),
        "risk": profile.risk,
    }
