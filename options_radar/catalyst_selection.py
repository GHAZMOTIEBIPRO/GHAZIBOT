from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd


def _default_confidence(source: str) -> float:
    lowered = source.lower()
    if "precision full-text" in lowered:
        return 0.90
    if "sec" in lowered:
        return 0.88
    if "fda" in lowered:
        return 0.62
    if "yahoo" in lowered:
        return 0.35
    return 0.5


def _source_bonus(source: str) -> float:
    lowered = source.lower()
    if "precision full-text" in lowered:
        return 5.0
    if "full-text" in lowered:
        return 4.0
    if "sec" in lowered:
        return 3.0
    if "fda" in lowered:
        return 1.0
    return 0.0


def _purpose_bonus(purpose: str) -> float:
    value = purpose.lower()
    if value in {"fda_regulatory_decision", "definitive_merger_acquisition"}:
        return 4.0
    if value in {"clinical_readout", "active_13d", "material_downside"}:
        return 3.0
    if value in {"strategic_contract", "capital_return_or_guidance"}:
        return 2.0
    if value == "secondary_news":
        return -3.0
    return 0.0


def _freshness_multiplier(value) -> float:
    text = str(value or "")[:10]
    try:
        event_date = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return 0.75
    age = max(0, (date.today() - event_date).days)
    if age <= 1:
        return 1.00
    if age <= 3:
        return 0.94
    if age <= 7:
        return 0.84
    if age <= 14:
        return 0.70
    if age <= 30:
        return 0.52
    return 0.30


def _value(row: pd.Series, key: str, default=None):
    value = row.get(key, default)
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    return value


def best_catalyst_map(frame: pd.DataFrame) -> dict[str, dict]:
    """Choose catalysts using source, confidence, materiality and freshness.

    A precise fresh SEC event must outrank a generic or stale mention. Negative
    dilution/risk evidence is combined with the best positive event so a bullish
    headline cannot hide a contemporaneous financing risk.
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
    if "purpose" not in working:
        working["purpose"] = ""
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
    working["freshness"] = [
        _freshness_multiplier(value) for value in working["event_date"]
    ]
    working["effective_score"] = (
        working["score"] * working["confidence"] * working["freshness"]
    )
    working["selection_rank"] = working["effective_score"] + [
        _source_bonus(str(source)) for source in working["source"]
    ] + [
        _purpose_bonus(str(purpose)) for purpose in working["purpose"]
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
        freshness = float(best["freshness"])
        effective_positive = max(0.0, float(best["score"]) * confidence * freshness)
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
            "freshness": freshness,
            "purpose": str(_value(best, "purpose", "")),
            "query_family": str(_value(best, "query_family", "")),
            "items": _value(best, "items", []),
            "negative_score": worst_effective,
        }
    return result
