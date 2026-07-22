from __future__ import annotations

import math

import pandas as pd


def _default_confidence(source: str) -> float:
    lowered = source.lower()
    if "sec" in lowered:
        return 1.0
    if "fda" in lowered:
        return 0.62
    if "yahoo" in lowered:
        return 0.35
    return 0.5


def _source_bonus(source: str) -> float:
    lowered = source.lower()
    if "sec" in lowered:
        return 3.0
    if "fda" in lowered:
        return 1.0
    return 0.0


def _value(row: pd.Series, key: str, default=None):
    value = row.get(key, default)
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    return value


def best_catalyst_map(frame: pd.DataFrame) -> dict[str, dict]:
    """Choose catalysts using confidence-weighted materiality.

    Secondary articles may support a setup, but they cannot outrank a comparable
    SEC/FDA event solely because a high-impact keyword appeared in a headline.
    Negative events are also confidence weighted before reducing the score.
    """

    if frame is None or frame.empty or "symbol" not in frame:
        return {}
    result: dict[str, dict] = {}
    working = frame.copy()
    working["score"] = pd.to_numeric(working.get("score"), errors="coerce").fillna(0.0)
    if "source" not in working:
        working["source"] = ""
    if "event_date" not in working:
        working["event_date"] = ""
    if "confidence" not in working:
        working["confidence"] = [
            _default_confidence(str(source)) for source in working["source"]
        ]
    else:
        working["confidence"] = pd.to_numeric(
            working["confidence"], errors="coerce"
        )
        missing = working["confidence"].isna()
        working.loc[missing, "confidence"] = [
            _default_confidence(str(source))
            for source in working.loc[missing, "source"]
        ]
    working["confidence"] = working["confidence"].clip(0.0, 1.0)
    working["effective_score"] = working["score"] * working["confidence"]
    working["selection_rank"] = working["effective_score"] + [
        _source_bonus(str(source)) for source in working["source"]
    ]

    for symbol, group in working[working["symbol"].astype(str) != ""].groupby("symbol"):
        positive = group[group["score"] > 0].sort_values(
            ["selection_rank", "event_date"], ascending=[False, False]
        )
        negative = group[group["score"] < 0].copy()
        best = positive.iloc[0] if not positive.empty else group.sort_values(
            "selection_rank", ascending=False
        ).iloc[0]
        worst_effective = (
            float(negative["effective_score"].min()) if not negative.empty else 0.0
        )
        confidence = float(best["confidence"])
        effective_positive = max(0.0, float(best["score"]) * confidence)
        combined = max(-25.0, min(25.0, effective_positive + worst_effective))
        result[str(symbol).upper()] = {
            "score": combined,
            "raw_score": float(best["score"]),
            "category": str(_value(best, "category", "")),
            "headline": str(_value(best, "headline", "")),
            "url": str(_value(best, "url", "")),
            "source": str(_value(best, "source", "")),
            "form": str(_value(best, "form", "")),
            "evidence": str(_value(best, "evidence", "")),
            "event_value": _value(best, "event_value"),
            "confidence": confidence,
            "purpose": str(_value(best, "purpose", "")),
            "negative_score": worst_effective,
        }
    return result
