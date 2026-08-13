from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adaptive_learning import stock_score_adjustment


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


@dataclass(frozen=True)
class StockDecision:
    raw_score: float
    market_regime_adjustment: float
    adaptive_learning_adjustment: float
    late_move_penalty: float
    chasing_risk: str
    decision_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_score": round(self.raw_score, 4),
            "market_regime_adjustment": round(self.market_regime_adjustment, 2),
            "adaptive_learning_adjustment": round(self.adaptive_learning_adjustment, 2),
            "late_move_penalty": round(self.late_move_penalty, 2),
            "chasing_risk": self.chasing_risk,
            "decision_score": round(self.decision_score, 4),
        }


def late_move_penalty(row: dict[str, Any]) -> tuple[float, str]:
    stage = str(row.get("stage") or "WATCH").upper()
    move = abs(_number(row.get("move_pct")))
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    official = bool(cause.get("official_confirmed"))
    if stage == "EXTENDED" or move >= 40:
        return -20.0, "HIGH"
    if move >= 30:
        return -8.0, "HIGH"
    if move >= 20 and not official:
        return -4.0, "MEDIUM"
    if move >= 15:
        return -2.0, "MEDIUM"
    return 0.0, "LOW"


def build_stock_decision(
    row: dict[str, Any],
    *,
    market_regime_adjustment: float,
    learning_model: dict[str, Any],
) -> StockDecision:
    raw = _number(row.get("score"))
    learning = stock_score_adjustment(learning_model, row)
    chase, risk = late_move_penalty(row)
    decision = max(0.0, min(100.0, raw + market_regime_adjustment + learning + chase))
    return StockDecision(
        raw_score=raw,
        market_regime_adjustment=market_regime_adjustment,
        adaptive_learning_adjustment=learning,
        late_move_penalty=chase,
        chasing_risk=risk,
        decision_score=decision,
    )
