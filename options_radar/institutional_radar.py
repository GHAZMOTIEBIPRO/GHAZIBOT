from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


STAGE_ORDER = {
    "WATCH": 0,
    "PRESSURE_BUILDING": 1,
    "IGNITION": 2,
    "EXPLOSION": 3,
    "EXTENDED": 4,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _get(candidate: Any, name: str, default: float = 0.0) -> float:
    if isinstance(candidate, Mapping):
        return _number(candidate.get(name), default)
    return _number(getattr(candidate, name, default), default)


def _move_quality(move_pct: float) -> float:
    """Reward early expansion and punish late/chasing conditions."""
    if move_pct < -8:
        return 5.0
    if move_pct < 0:
        return 18.0
    if move_pct < 1:
        return 35.0
    if move_pct <= 4:
        return 72.0
    if move_pct <= 10:
        return 100.0
    if move_pct <= 16:
        return 86.0
    if move_pct <= 24:
        return 62.0
    if move_pct <= 35:
        return 30.0
    return 5.0


def _earlyness(move_pct: float, acceleration: float, supply: float, news: float) -> float:
    base = _move_quality(move_pct)
    if 0.5 <= move_pct <= 12:
        base += acceleration * 0.16
        base += max(0.0, supply - 55.0) * 0.08
        base += max(0.0, news - 55.0) * 0.06
    if move_pct > 24:
        base -= (move_pct - 24.0) * 2.2
    return _clamp(base)


def _acceleration(candidate: Any, previous: Mapping[str, Any] | None) -> tuple[float, list[str]]:
    if not previous:
        return 0.0, []

    score = _get(candidate, "score")
    move = _get(candidate, "move_pct")
    volume = _get(candidate, "volume")
    turnover = _get(candidate, "turnover_pct")

    previous_score = _number(previous.get("base_score"), _number(previous.get("score")))
    previous_move = _number(previous.get("move_pct"))
    previous_volume = _number(previous.get("volume"))
    previous_turnover = _number(previous.get("turnover_pct"))

    score_delta = score - previous_score
    move_delta = move - previous_move
    turnover_delta = turnover - previous_turnover
    volume_growth = volume / previous_volume if previous_volume > 0 else 1.0

    components = 0.0
    reasons: list[str] = []
    if score_delta > 0:
        components += _clamp(score_delta * 3.0, 0.0, 30.0)
    if move_delta > 0:
        components += _clamp(move_delta * 9.0, 0.0, 28.0)
    if turnover_delta > 0:
        components += _clamp(turnover_delta * 24.0, 0.0, 22.0)
    if volume_growth > 1.0:
        components += _clamp((volume_growth - 1.0) * 35.0, 0.0, 20.0)

    acceleration = _clamp(components)
    if acceleration >= 45:
        reasons.append(
            f"تسارع واضح بين الجولات {acceleration:.0f}/100 "
            f"(السعر Δ {move_delta:+.1f} نقطة، الحجم ×{volume_growth:.2f})"
        )
    elif acceleration >= 25:
        reasons.append(f"التسارع بدأ يرتفع {acceleration:.0f}/100")
    return acceleration, reasons


@dataclass(frozen=True)
class InstitutionalAssessment:
    score: float
    stage: str
    confidence: str
    earlyness: float
    anomaly: float
    acceleration: float
    risk_penalty: float
    send_priority: float
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]


def assess_candidate(
    candidate: Any,
    previous: Mapping[str, Any] | None = None,
) -> InstitutionalAssessment:
    """Convert raw full-market signals into a conservative institutional-style score.

    This does not claim to identify institutions or true options sweeps. It scores
    observable anomalies, acceleration, supply pressure, catalyst quality and
    whether the move is still early enough to be actionable.
    """

    supply = _get(candidate, "supply_score")
    turnover = _get(candidate, "turnover_score")
    volume = _get(candidate, "volume_score")
    news = _get(candidate, "news_score")
    structural = _get(candidate, "structural_score")
    base_score = _get(candidate, "score")
    move_pct = _get(candidate, "move_pct")
    price = _get(candidate, "price")
    market_cap = _get(candidate, "market_cap")
    dollar_volume = _get(candidate, "dollar_volume")

    acceleration, acceleration_reasons = _acceleration(candidate, previous)
    anomaly = _clamp(turnover * 0.42 + volume * 0.28 + acceleration * 0.30)
    earlyness = _earlyness(move_pct, acceleration, supply, news)
    move_quality = _move_quality(move_pct)

    raw = (
        supply * 0.20
        + anomaly * 0.24
        + news * 0.16
        + min(100.0, structural) * 0.08
        + move_quality * 0.12
        + earlyness * 0.12
        + base_score * 0.08
    )

    risk_penalty = 0.0
    blockers: list[str] = []
    if move_pct > 24:
        risk_penalty += min(28.0, (move_pct - 24.0) * 1.8)
        blockers.append("الحركة أصبحت متأخرة نسبيًا؛ خطر مطاردة السعر مرتفع")
    if price and price < 1.0:
        risk_penalty += 7.0
    if 0 < market_cap < 20_000_000:
        risk_penalty += 7.0
    if 0 < dollar_volume < 500_000:
        risk_penalty += 12.0
        blockers.append("السيولة الدولارية ما زالت ضعيفة")
    if move_pct < -5 and acceleration < 25:
        risk_penalty += 18.0
        blockers.append("السعر سلبي بدون تسارع تعويضي")

    score = _clamp(raw - risk_penalty)

    if move_pct >= 35 or (move_pct >= 25 and earlyness < 35):
        stage = "EXTENDED"
    elif score >= 84 and anomaly >= 70 and move_pct >= 3:
        stage = "EXPLOSION"
    elif score >= 73 and anomaly >= 55 and earlyness >= 45:
        stage = "IGNITION"
    elif score >= 62 and earlyness >= 55:
        stage = "PRESSURE_BUILDING"
    else:
        stage = "WATCH"

    if blockers and stage in {"PRESSURE_BUILDING", "IGNITION"} and score < 76:
        stage = "WATCH"

    confidence = "A" if score >= 86 and anomaly >= 72 else "B" if score >= 75 else "C" if score >= 64 else "D"
    send_priority = _clamp(score * 0.58 + earlyness * 0.24 + acceleration * 0.18)
    if stage == "EXTENDED":
        send_priority = min(send_priority, 45.0)

    reasons: list[str] = []
    reasons.extend(acceleration_reasons)
    if anomaly >= 70:
        reasons.append(f"شذوذ سعري/سيولة قوي {anomaly:.0f}/100")
    elif anomaly >= 55:
        reasons.append(f"شذوذ سعري/سيولة يتصاعد {anomaly:.0f}/100")
    if earlyness >= 70:
        reasons.append(f"الحركة ما زالت مبكرة {earlyness:.0f}/100")
    if supply >= 75:
        reasons.append(f"ضغط العرض/المعروض مناسب {supply:.0f}/100")
    if news >= 70:
        reasons.append(f"محفز خبري مرتفع الجودة {news:.0f}/100")
    if risk_penalty >= 12:
        reasons.append(f"خصم مخاطر {risk_penalty:.0f} نقطة")

    return InstitutionalAssessment(
        score=round(score, 2),
        stage=stage,
        confidence=confidence,
        earlyness=round(earlyness, 2),
        anomaly=round(anomaly, 2),
        acceleration=round(acceleration, 2),
        risk_penalty=round(risk_penalty, 2),
        send_priority=round(send_priority, 2),
        reasons=tuple(reasons),
        blockers=tuple(blockers),
    )


def should_promote(previous_stage: str | None, current_stage: str, score_delta: float) -> bool:
    """Only alert on a real state transition or material score improvement."""
    prior = STAGE_ORDER.get(str(previous_stage or "WATCH"), 0)
    current = STAGE_ORDER.get(current_stage, 0)
    return current > prior or score_delta >= 9.0
