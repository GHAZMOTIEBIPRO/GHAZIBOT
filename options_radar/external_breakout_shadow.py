"""Research-only breakout evidence with explicit data-quality gates.

This adapter never fetches data, creates execution signals, or bypasses V11.
Callers must prove that the final bar is complete, timestamped, and adjusted.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from math import isfinite
from statistics import mean


@dataclass(frozen=True)
class BreakoutEvidence:
    status: str
    distance_to_high_pct: float | None
    volume_ratio: float | None
    range_contraction: float | None
    reasons: tuple[str, ...]
    research_only: bool = True


def _as_floats(values: Sequence[float]) -> list[float] | None:
    try:
        converted = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    return converted if all(isfinite(value) for value in converted) else None


def _timestamps_valid(
    timestamps: Sequence[datetime | str] | None,
    *,
    count: int,
    as_of: datetime | None,
) -> bool:
    if timestamps is None or len(timestamps) != count:
        return False
    parsed: list[datetime] = []
    for value in timestamps:
        try:
            item = (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str)
                else value
            )
        except (TypeError, ValueError):
            return False
        if not isinstance(item, datetime) or item.tzinfo is None:
            return False
        parsed.append(item.astimezone(timezone.utc))
    if any(left >= right for left, right in pairwise(parsed)):
        return False
    if as_of is not None:
        if as_of.tzinfo is None:
            return False
        if parsed[-1] > as_of.astimezone(timezone.utc):
            return False
    return True


def breakout_evidence(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    *,
    lookback: int = 20,
    bar_timestamps: Sequence[datetime | str] | None = None,
    as_of: datetime | None = None,
    last_bar_complete: bool = False,
    prices_adjusted: bool | None = None,
) -> BreakoutEvidence:
    """Evaluate completed adjusted daily bars without future leakage.

    The explicit gates are intentionally strict for historical research:
    timestamp provenance, an as-of boundary, completed final bar, and a
    verified adjusted-price basis are required before any feature is computed.
    """
    n = len(closes)
    if not last_bar_complete:
        return BreakoutEvidence(
            "INSUFFICIENT_DATA", None, None, None, ("last_bar_incomplete_or_unverified",)
        )
    if prices_adjusted is not True:
        return BreakoutEvidence(
            "INSUFFICIENT_DATA", None, None, None, ("price_adjustment_unverified",)
        )
    if as_of is None or not _timestamps_valid(bar_timestamps, count=n, as_of=as_of):
        return BreakoutEvidence(
            "INSUFFICIENT_DATA", None, None, None, ("timestamp_provenance_or_as_of_invalid",)
        )
    if lookback < 10 or n < max(lookback * 2, 40) or not (
        len(highs) == len(lows) == len(volumes) == n
    ):
        return BreakoutEvidence(
            "INSUFFICIENT_DATA", None, None, None, ("missing_daily_history",)
        )
    high_values = _as_floats(highs)
    low_values = _as_floats(lows)
    close_values = _as_floats(closes)
    volume_values = _as_floats(volumes)
    if any(values is None for values in (high_values, low_values, close_values, volume_values)):
        return BreakoutEvidence("INVALID_DATA", None, None, None, ("invalid_bars",))
    assert high_values is not None
    assert low_values is not None
    assert close_values is not None
    assert volume_values is not None
    if any(value < 0 for value in volume_values):
        return BreakoutEvidence("INVALID_DATA", None, None, None, ("invalid_volume",))
    if any(
        high < max(low, close) or low > close or low <= 0 or close <= 0
        for high, low, close in zip(high_values, low_values, close_values)
    ):
        return BreakoutEvidence("INVALID_DATA", None, None, None, ("inconsistent_ohlc",))

    baseline_volume = mean(volume_values[-lookback - 1 : -1])
    if baseline_volume <= 0:
        return BreakoutEvidence("INSUFFICIENT_DATA", None, None, None, ("missing_volume",))
    prior_high = max(high_values[-lookback - 1 : -1])
    distance = 100 * (prior_high - close_values[-1]) / prior_high
    volume_ratio = volume_values[-1] / baseline_volume
    recent_range = mean(
        (high - low) / close
        for high, low, close in zip(
            high_values[-5:], low_values[-5:], close_values[-5:]
        )
    )
    earlier_range = mean(
        (high - low) / close
        for high, low, close in zip(
            high_values[-lookback:-5],
            low_values[-lookback:-5],
            close_values[-lookback:-5],
        )
    )
    contraction = recent_range / earlier_range if earlier_range > 0 else None
    reasons: list[str] = []
    if contraction is not None and contraction <= 0.75:
        reasons.append("range_contraction")
    if 0 <= distance <= 5:
        reasons.append("near_prior_high")
    if volume_ratio >= 1.5:
        reasons.append("volume_expansion")
    if distance < 0 and volume_ratio >= 1.5:
        status = "BREAKOUT_RESEARCH"
    elif "range_contraction" in reasons and "near_prior_high" in reasons:
        status = "COILING_RESEARCH"
    else:
        status = "WATCH_RESEARCH"
    return BreakoutEvidence(
        status,
        round(distance, 3),
        round(volume_ratio, 3),
        round(contraction, 3) if contraction is not None else None,
        tuple(reasons),
    )
