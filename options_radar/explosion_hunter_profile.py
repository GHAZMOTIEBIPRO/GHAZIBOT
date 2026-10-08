"""Research-only configuration for aggressive 100% explosion hunting.

Do not interpret the target as a probability or a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass


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


def classify_candidate(row: dict, *, profile: HunterProfile = PROFILE) -> dict:
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
    evidence = bool(quote_time) and bool(catalyst_url)
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
