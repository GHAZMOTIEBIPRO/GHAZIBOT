"""Research-only breakout feature adapter inspired by Qullamaggie-style setups.

Independent observations, not execution signals. No data fetching or fabricated
catalysts. Keep separate from the production V11 option gate.
"""
from __future__ import annotations

from dataclasses import dataclass
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


def breakout_evidence(highs: list[float], lows: list[float], closes: list[float],
                      volumes: list[float], *, lookback: int = 20) -> BreakoutEvidence:
    """Evaluate completed daily bars; never use the active candle as confirmation."""
    n = len(closes)
    if lookback < 10 or n < max(lookback * 2, 40) or not (len(highs) == len(lows) == len(volumes) == n):
        return BreakoutEvidence("INSUFFICIENT_DATA", None, None, None, ("missing_daily_history",))
    values = highs + lows + closes + volumes
    if not all(isfinite(v) for v in values) or any(v < 0 for v in volumes):
        return BreakoutEvidence("INVALID_DATA", None, None, None, ("invalid_bars",))
    if any(h < max(l, c) or l > c or l <= 0 for h, l, c in zip(highs, lows, closes)):
        return BreakoutEvidence("INVALID_DATA", None, None, None, ("inconsistent_ohlc",))
    baseline_volume = mean(volumes[-lookback-1:-1])
    if baseline_volume <= 0:
        return BreakoutEvidence("INSUFFICIENT_DATA", None, None, None, ("missing_volume",))
    prior_high = max(highs[-lookback-1:-1])
    distance = 100 * (prior_high - closes[-1]) / prior_high
    volume_ratio = volumes[-1] / baseline_volume
    recent_range = mean((h - l) / c for h, l, c in zip(highs[-5:], lows[-5:], closes[-5:]))
    earlier_range = mean((h - l) / c for h, l, c in zip(highs[-lookback:-5], lows[-lookback:-5], closes[-lookback:-5]))
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
    return BreakoutEvidence(status, round(distance, 3), round(volume_ratio, 3),
                            round(contraction, 3) if contraction is not None else None,
                            tuple(reasons))
