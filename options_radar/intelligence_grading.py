from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


HORIZONS_MINUTES: tuple[tuple[str, int], ...] = (
    ("15m", 15),
    ("60m", 60),
    ("390m", 390),
    ("1d", 1440),
    ("3d", 4320),
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def register_alert(
    state: dict[str, Any],
    *,
    alert_id: str,
    kind: str,
    symbol: str,
    direction: str,
    baseline_underlying: float,
    baseline_instrument: float = 0.0,
    score: float = 0.0,
    evidence_signature: str = "",
    sent_at: datetime | None = None,
) -> None:
    sent_at = (sent_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    outcomes = state.setdefault("outcomes", {})
    if alert_id in outcomes:
        return
    outcomes[alert_id] = {
        "kind": kind,
        "symbol": symbol.upper(),
        "direction": direction.upper(),
        "sent_at": sent_at.isoformat(),
        "baseline_underlying": round(max(0.0, baseline_underlying), 8),
        "baseline_instrument": round(max(0.0, baseline_instrument), 8),
        "score": round(score, 4),
        "evidence_signature": evidence_signature[:180],
        "checkpoints": {},
    }


def grade_alerts(
    state: dict[str, Any],
    *,
    underlying_prices: dict[str, float],
    instrument_prices: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    instrument_prices = instrument_prices or {}
    outcomes = state.setdefault("outcomes", {})

    for alert_id, record in list(outcomes.items()):
        if not isinstance(record, dict):
            continue
        sent_at = _parse(record.get("sent_at"))
        if sent_at is None:
            continue
        elapsed = max(0.0, (now - sent_at).total_seconds() / 60.0)
        symbol = str(record.get("symbol") or "").upper()
        current_underlying = _num(underlying_prices.get(symbol))
        baseline_underlying = _num(record.get("baseline_underlying"))
        current_instrument = _num(instrument_prices.get(alert_id))
        baseline_instrument = _num(record.get("baseline_instrument"))
        checkpoints = record.setdefault("checkpoints", {})
        direction = str(record.get("direction") or "UP").upper()
        sign = -1.0 if direction in {"PUT", "DOWN", "BEARISH"} else 1.0

        for label, minutes in HORIZONS_MINUTES:
            if elapsed < minutes or label in checkpoints:
                continue
            if current_underlying <= 0 or baseline_underlying <= 0:
                continue
            raw_underlying = (current_underlying / baseline_underlying - 1.0) * 100.0
            directional = raw_underlying * sign
            instrument_return = None
            if current_instrument > 0 and baseline_instrument > 0:
                instrument_return = (current_instrument / baseline_instrument - 1.0) * 100.0
            checkpoints[label] = {
                "graded_at": now.isoformat(),
                "underlying_price": round(current_underlying, 8),
                "underlying_return_pct": round(raw_underlying, 4),
                "directional_return_pct": round(directional, 4),
                "instrument_price": round(current_instrument, 8) if current_instrument > 0 else None,
                "instrument_return_pct": round(instrument_return, 4) if instrument_return is not None else None,
                "direction_correct": directional > 0,
            }

    # Bound old completed records, preserving the most recent evidence for calibration.
    if len(outcomes) > 1200:
        ordered = sorted(
            outcomes.items(),
            key=lambda item: str((item[1] or {}).get("sent_at") or "") if isinstance(item[1], dict) else "",
            reverse=True,
        )
        state["outcomes"] = dict(ordered[:900])
    scorecard = build_scorecard(state)
    state["self_grading_scorecard"] = scorecard
    return scorecard


def build_scorecard(state: dict[str, Any]) -> dict[str, Any]:
    outcomes = state.get("outcomes") if isinstance(state.get("outcomes"), dict) else {}
    horizon_stats: dict[str, dict[str, Any]] = {}
    for label, _ in HORIZONS_MINUTES:
        directional: list[float] = []
        instrument: list[float] = []
        wins = 0
        for record in outcomes.values():
            if not isinstance(record, dict):
                continue
            checkpoints = record.get("checkpoints") if isinstance(record.get("checkpoints"), dict) else {}
            point = checkpoints.get(label) if isinstance(checkpoints.get(label), dict) else None
            if not point:
                continue
            value = _num(point.get("directional_return_pct"), float("nan"))
            if math.isfinite(value):
                directional.append(value)
                wins += 1 if value > 0 else 0
            instrument_value = point.get("instrument_return_pct")
            if instrument_value is not None:
                number = _num(instrument_value, float("nan"))
                if math.isfinite(number):
                    instrument.append(number)
        n = len(directional)
        horizon_stats[label] = {
            "sample_size": n,
            "direction_hit_rate": round(wins / n, 4) if n else None,
            "mean_directional_return_pct": round(sum(directional) / n, 4) if n else None,
            "mean_instrument_return_pct": round(sum(instrument) / len(instrument), 4) if instrument else None,
        }
    return {
        "alert_records": len(outcomes),
        "horizons": horizon_stats,
        "score_is_probability": False,
        "learning_note": "Outcome grading is descriptive until each evidence bucket has a sufficient sample; hard safety/data gates are never relaxed automatically.",
    }
