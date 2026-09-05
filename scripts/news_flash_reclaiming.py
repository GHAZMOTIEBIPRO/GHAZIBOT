from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _normalise(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    output = frame.copy()
    required = {"Close", "High", "Low", "Volume"}
    if not required.issubset(output.columns):
        return pd.DataFrame()
    index = pd.to_datetime(output.index, errors="coerce")
    valid = ~index.isna()
    output = output.loc[valid].copy()
    index = index[valid]
    if getattr(index, "tz", None) is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    output.index = index
    for column in required:
        output[column] = pd.to_numeric(output[column], errors="coerce")
    return output.dropna(subset=["Close", "High", "Low"]).sort_index()


def reclaim_metrics(
    frame: pd.DataFrame | None,
    event_at: datetime,
    bias: str,
) -> dict[str, Any] | None:
    """Measure a post-news reclaim without pretending it is a trade signal.

    The reclaim is anchored to the event timestamp. For positive news, price must
    regain the event-anchored VWAP and close a completed 5-minute bar above the
    prior completed 5-minute high with supportive volume. Negative-news logic is
    the directional mirror. An in-progress five-minute bucket is never allowed
    to promote a reclaim state.
    """

    data = _normalise(frame)
    if data.empty:
        return None
    event_at = event_at.astimezone(timezone.utc)
    after = data[data.index >= pd.Timestamp(event_at)].copy()
    if len(after) < 8:
        return None

    volume = after["Volume"].fillna(0.0).clip(lower=0.0)
    typical = (after["High"] + after["Low"] + after["Close"]) / 3.0
    cumulative_volume = float(volume.sum())
    if cumulative_volume <= 0:
        return None
    anchored_vwap = float((typical * volume).sum() / cumulative_volume)
    current = float(after["Close"].dropna().iloc[-1])

    bars = (
        after.resample("5min", label="right", closed="right")
        .agg({"Close": "last", "High": "max", "Low": "min", "Volume": "sum"})
        .dropna(subset=["Close", "High", "Low"])
    )
    if not bars.empty and bars.index[-1] > after.index[-1]:
        bars = bars.iloc[:-1]
    if len(bars) < 3:
        return None

    latest = bars.iloc[-1]
    prior = bars.iloc[-2]
    history = bars.iloc[:-1]
    baseline_volume = float(history["Volume"].tail(6).median()) if not history.empty else 0.0
    latest_volume = float(latest["Volume"])
    volume_ratio = latest_volume / baseline_volume if baseline_volume > 0 else 0.0

    direction = str(bias or "NEUTRAL").upper()
    if direction == "POSITIVE":
        vwap_reclaimed = current > anchored_vwap
        structure_reclaimed = float(latest["Close"]) > float(prior["High"])
    elif direction == "NEGATIVE":
        vwap_reclaimed = current < anchored_vwap
        structure_reclaimed = float(latest["Close"]) < float(prior["Low"])
    else:
        return None

    volume_confirmed = volume_ratio >= 1.15
    reclaiming = bool(vwap_reclaimed and structure_reclaimed and volume_confirmed)
    return {
        "anchored_vwap": round(anchored_vwap, 4),
        "current": round(current, 4),
        "vwap_reclaimed": bool(vwap_reclaimed),
        "structure_5m_reclaimed": bool(structure_reclaimed),
        "volume_ratio_5m": round(volume_ratio, 3),
        "volume_confirmed": bool(volume_confirmed),
        "reclaiming": reclaiming,
        "decision_authority": False,
        "label": "post_news_reclaim_proxy",
    }
