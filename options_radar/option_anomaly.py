from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ContractVolumeAnomaly:
    ready: bool
    observations: int
    prior_five_day_average: float | None
    historical_median: float | None
    volume_to_median_ratio: float | None
    empirical_percentile: float | None
    robust_z: float | None
    score: float


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _volume_series(history: pd.DataFrame) -> pd.Series:
    if history is None or history.empty:
        return pd.Series(dtype="float64")
    column = "Volume" if "Volume" in history else "volume" if "volume" in history else None
    if not column:
        return pd.Series(dtype="float64")
    volume = pd.to_numeric(history[column], errors="coerce").clip(lower=0)
    if isinstance(history.index, pd.DatetimeIndex):
        today = pd.Timestamp.now(tz="UTC").date()
        index = pd.to_datetime(history.index, utc=True, errors="coerce")
        volume = volume[index.date < today]
    else:
        volume = volume.iloc[:-1] if len(volume) > 1 else volume.iloc[0:0]
    return volume.dropna()


def analyze_contract_volume_anomaly(
    current_volume: Any,
    history: pd.DataFrame,
    *,
    min_observations: int = 5,
    max_observations: int = 20,
) -> ContractVolumeAnomaly:
    """Score current option volume against the contract's own prior sessions.

    The result is research/ranking evidence only. It does not identify trade
    initiation, opening/closing intent, institutional participation, or a sweep.
    """
    current = _finite(current_volume)
    prior = _volume_series(history).tail(max(1, int(max_observations)))
    observations = int(len(prior))
    prior_five = prior.tail(5)
    prior_average = float(prior_five.mean()) if not prior_five.empty else None

    if current is None or current < 0 or prior.empty:
        return ContractVolumeAnomaly(
            False,
            observations,
            prior_average,
            None,
            None,
            None,
            None,
            0.0,
        )

    median = float(prior.median())
    if median <= 0:
        positive = prior[prior > 0]
        median = float(positive.median()) if not positive.empty else 0.0

    ratio = current / median if median > 0 else None
    below = int((prior < current).sum())
    equal = int((prior == current).sum())
    percentile = (below + 0.5 * equal) / observations if observations else None

    absolute_deviation = (prior - float(prior.median())).abs()
    mad = float(absolute_deviation.median()) if not absolute_deviation.empty else 0.0
    robust_z: float | None
    if mad > 0:
        robust_z = 0.6745 * (current - float(prior.median())) / mad
    elif ratio is not None:
        robust_z = max(0.0, (ratio - 1.0) * 3.0)
    else:
        robust_z = None

    ready = observations >= max(1, int(min_observations))
    if not ready or ratio is None or percentile is None:
        score = 0.0
    else:
        ratio_component = max(
            0.0,
            min(55.0, math.log2(max(ratio, 1.0)) / 2.5 * 55.0),
        )
        percentile_component = max(
            0.0,
            min(30.0, (percentile - 0.75) / 0.25 * 30.0),
        )
        z_component = max(
            0.0,
            min(15.0, max(0.0, robust_z or 0.0) / 6.0 * 15.0),
        )
        score = ratio_component + percentile_component + z_component

    return ContractVolumeAnomaly(
        ready,
        observations,
        prior_average,
        round(median, 4) if median > 0 else None,
        round(ratio, 4) if ratio is not None else None,
        round(percentile, 4) if percentile is not None else None,
        round(robust_z, 4) if robust_z is not None else None,
        round(max(0.0, min(100.0, score)), 2),
    )
