from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalise(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty or "Volume" not in frame:
        return pd.DataFrame(columns=["Volume"])
    out = frame.copy()
    out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce").fillna(0.0)
    out = out[out["Volume"] >= 0]
    return out


def _regular_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    local = frame.copy()
    local["_ny"] = local.index.tz_convert(NEW_YORK)
    clock = local["_ny"].dt.time
    local = local[(clock >= REGULAR_OPEN) & (clock <= REGULAR_CLOSE)]
    local["_session"] = local["_ny"].dt.date
    local["_minute"] = local["_ny"].dt.hour * 60 + local["_ny"].dt.minute
    return local


@dataclass(frozen=True)
class TimeNormalizedVolume:
    available: bool
    ratio: float | None
    pace_percentile: float | None
    current_cumulative_volume: float | None
    historical_median_cumulative_volume: float | None
    sample_sessions: int
    session_date: str
    cutoff_minute_et: int | None
    cutoff_clock_et: str
    source_role: str
    research_only: bool = True
    live_score_adjustment: bool = False
    decision_authority: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def time_normalized_rvol(
    bars: pd.DataFrame | None,
    *,
    now: datetime | None = None,
    minimum_sessions: int = 5,
    maximum_sessions: int = 20,
) -> TimeNormalizedVolume:
    """Compare current cumulative regular-session volume with the same clock time historically.

    This is a research feature. The current session is excluded from the historical
    baseline and no bar later than the current New York clock minute is used.
    """

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    reference = reference.astimezone(timezone.utc)
    local_now = reference.astimezone(NEW_YORK)
    session_date = local_now.date()
    minute = local_now.hour * 60 + local_now.minute
    open_minute = REGULAR_OPEN.hour * 60 + REGULAR_OPEN.minute
    close_minute = REGULAR_CLOSE.hour * 60 + REGULAR_CLOSE.minute

    frame = _regular_rows(_normalise(bars))
    if frame.empty:
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=None,
            historical_median_cumulative_volume=None,
            sample_sessions=0,
            session_date=session_date.isoformat(),
            cutoff_minute_et=None,
            cutoff_clock_et="",
            source_role="intraday_bar_volume_profile",
            reason="no_regular_session_5m_bars",
        )

    if minute < open_minute:
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=None,
            historical_median_cumulative_volume=None,
            sample_sessions=0,
            session_date=session_date.isoformat(),
            cutoff_minute_et=None,
            cutoff_clock_et=local_now.strftime("%H:%M"),
            source_role="intraday_bar_volume_profile",
            reason="premarket_not_comparable_to_regular_session_profile",
        )

    completed_cutoff = (minute // 5) * 5 - 5
    cutoff = min(completed_cutoff, close_minute)
    if cutoff < open_minute:
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=None,
            historical_median_cumulative_volume=None,
            sample_sessions=0,
            session_date=session_date.isoformat(),
            cutoff_minute_et=None,
            cutoff_clock_et=local_now.strftime("%H:%M"),
            source_role="intraday_bar_volume_profile",
            reason="no_completed_regular_session_5m_bar",
        )

    current = frame[
        (frame["_session"] == session_date)
        & (frame["_minute"] <= cutoff)
    ]
    if current.empty:
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=None,
            historical_median_cumulative_volume=None,
            sample_sessions=0,
            session_date=session_date.isoformat(),
            cutoff_minute_et=cutoff,
            cutoff_clock_et=f"{cutoff // 60:02d}:{cutoff % 60:02d}",
            source_role="intraday_bar_volume_profile",
            reason="current_session_bars_unavailable",
        )

    current_volume = float(current["Volume"].sum())
    historical: list[tuple[Any, float]] = []
    for historical_date, group in frame[frame["_session"] < session_date].groupby("_session"):
        comparable = group[group["_minute"] <= cutoff]
        if comparable.empty:
            continue
        volume = float(comparable["Volume"].sum())
        if volume > 0:
            historical.append((historical_date, volume))

    historical.sort(key=lambda item: item[0], reverse=True)
    values = [value for _, value in historical[: max(1, maximum_sessions)]]
    if len(values) < max(2, minimum_sessions):
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=round(current_volume, 2),
            historical_median_cumulative_volume=None,
            sample_sessions=len(values),
            session_date=session_date.isoformat(),
            cutoff_minute_et=cutoff,
            cutoff_clock_et=f"{cutoff // 60:02d}:{cutoff % 60:02d}",
            source_role="intraday_bar_volume_profile",
            reason="insufficient_comparable_sessions",
        )

    baseline = float(median(values))
    ratio = current_volume / baseline if baseline > 0 else None
    percentile = (
        sum(value <= current_volume for value in values) / len(values) * 100.0
        if values
        else None
    )
    return TimeNormalizedVolume(
        available=ratio is not None,
        ratio=round(ratio, 4) if ratio is not None else None,
        pace_percentile=round(percentile, 2) if percentile is not None else None,
        current_cumulative_volume=round(current_volume, 2),
        historical_median_cumulative_volume=round(baseline, 2),
        sample_sessions=len(values),
        session_date=session_date.isoformat(),
        cutoff_minute_et=cutoff,
        cutoff_clock_et=f"{cutoff // 60:02d}:{cutoff % 60:02d}",
        source_role="same-clock regular-session cumulative 5m volume",
        reason="",
    )
