from __future__ import annotations

from typing import Any

from .adaptive_learning import options_score_adjustment


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def apply_options_learning(row: dict[str, Any], learning_model: dict[str, Any]) -> dict[str, Any]:
    raw = _number(row.get("score"))
    adjustment = options_score_adjustment(learning_model, row)
    combined = max(0.0, min(100.0, raw + adjustment))
    return {
        "raw_score": round(raw, 4),
        "adaptive_learning_adjustment": round(adjustment, 2),
        "decision_score": round(combined, 4),
    }
