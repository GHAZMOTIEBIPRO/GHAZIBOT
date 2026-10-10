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
REGULAR_LAST_BAR = time(15, 55)


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
    out = out[~out.index.duplicated(keep="last")]
    out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce").fillna(0.0)
    out = out[out["Volume"] >= 0]
    return out


def _regular_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    local = frame.copy()
    local["_ny"] = local.index.tz_convert(NEW_YORK)
    clock = local["_ny"].dt.time
    local = local[(clock >= REGULAR_OPEN) & (clock < REGULAR_CLOSE)]
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
    latest_current_bar_clock_et: str = ""
    current_bar_lag_minutes: int | None = None
    expected_completed_slots: int = 0
    observed_current_slots: int = 0
    current_slot_coverage_pct: float | None = None
    profile_quality: str = "UNKNOWN"
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
    maximum_current_lag_minutes: int = 10,
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
    last_bar_minute = REGULAR_LAST_BAR.hour * 60 + REGULAR_LAST_BAR.minute

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
    cutoff = min(completed_cutoff, last_bar_minute)
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

    current = current.sort_values("_minute")
    current_volume = float(current["Volume"].sum())
    latest_current_minute = int(current["_minute"].max())
    current_lag = max(0, cutoff - latest_current_minute)
    expected_slots = max(1, ((cutoff - open_minute) // 5) + 1)
    observed_slots = int(current["_minute"].nunique())
    coverage_pct = min(100.0, observed_slots / expected_slots * 100.0)

    if current_lag > max(0, int(maximum_current_lag_minutes)):
        return TimeNormalizedVolume(
            available=False,
            ratio=None,
            pace_percentile=None,
            current_cumulative_volume=round(current_volume, 2),
            historical_median_cumulative_volume=None,
            sample_sessions=0,
            session_date=session_date.isoformat(),
            cutoff_minute_et=cutoff,
            cutoff_clock_et=f"{cutoff // 60:02d}:{cutoff % 60:02d}",
            source_role="same-clock regular-session cumulative 5m volume",
            latest_current_bar_clock_et=(
                f"{latest_current_minute // 60:02d}:{latest_current_minute % 60:02d}"
            ),
            current_bar_lag_minutes=current_lag,
            expected_completed_slots=expected_slots,
            observed_current_slots=observed_slots,
            current_slot_coverage_pct=round(coverage_pct, 2),
            profile_quality="STALE_OR_SPARSE",
            reason="current_session_profile_too_stale_or_sparse",
        )

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
            latest_current_bar_clock_et=(
                f"{latest_current_minute // 60:02d}:{latest_current_minute % 60:02d}"
            ),
            current_bar_lag_minutes=current_lag,
            expected_completed_slots=expected_slots,
            observed_current_slots=observed_slots,
            current_slot_coverage_pct=round(coverage_pct, 2),
            profile_quality="INSUFFICIENT_HISTORY",
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
        latest_current_bar_clock_et=(
            f"{latest_current_minute // 60:02d}:{latest_current_minute % 60:02d}"
        ),
        current_bar_lag_minutes=current_lag,
        expected_completed_slots=expected_slots,
        observed_current_slots=observed_slots,
        current_slot_coverage_pct=round(coverage_pct, 2),
        profile_quality=(
            "GOOD" if coverage_pct >= 80.0 else "SPARSE_BUT_CURRENT"
        ),
        reason="",
    )
