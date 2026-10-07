from __future__ import annotations

import math
from typing import Any


_EVENT_POTENCY = {
    "FDA_APPROVAL": 98.0,
    "FDA_CRL": 98.0,
    "FDA_HOLD_LIFTED": 90.0,
    "FDA_CLINICAL_HOLD": 94.0,
    "TRIAL_POSITIVE": 92.0,
    "TRIAL_FAILED": 96.0,
    "MERGER_DEFINITIVE": 96.0,
    "MERGER_TERMINATED": 96.0,
    "TENDER_OFFER": 96.0,
    "ACQUISITION": 88.0,
    "MATERIAL_CONTRACT": 82.0,
    "PARTNERSHIP": 70.0,
    "GUIDANCE_RAISE": 82.0,
    "GUIDANCE_CUT": 88.0,
    "REGISTERED_DIRECT": 94.0,
    "PUBLIC_OFFERING": 92.0,
    "ATM": 92.0,
    "CONVERTIBLE_FINANCING": 84.0,
    "BANKRUPTCY": 100.0,
    "DELISTING": 92.0,
    "STRATEGIC_OWNERSHIP_13D": 82.0,
    "INSIDER_OPEN_MARKET_PURCHASE": 66.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pct(value: Any) -> float:
    number = _number(value)
    if abs(number) <= 1.0 and number != 0:
        number *= 100.0
    return number


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _freshness(age_days: float) -> float:
    if age_days <= 1:
        return 100.0
    if age_days <= 3:
        return 90.0
    if age_days <= 7:
        return 76.0
    if age_days <= 14:
        return 55.0
    if age_days <= 30:
        return 30.0
    return 10.0


def _supply_amplification(stock: dict[str, Any]) -> tuple[float, list[str]]:
    float_shares = 0.0
    for key in (
        "effective_float_estimate",
        "effective_float",
        "public_float_shares",
        "float_shares",
        "float",
    ):
        value = _number(stock.get(key))
        if value > 0:
            float_shares = value
            break
    short_float = _pct(
        stock.get("short_float_pct")
        if stock.get("short_float_pct") is not None
        else stock.get("short_float")
    )
    reasons: list[str] = []
    score = 35.0
    if 0 < float_shares <= 2_000_000:
        score = 100.0
        reasons.append(f"Float شديد الانخفاض ≈ {float_shares/1_000_000:.2f}M")
    elif float_shares <= 5_000_000 and float_shares > 0:
        score = 90.0
        reasons.append(f"Float منخفض ≈ {float_shares/1_000_000:.1f}M")
    elif float_shares <= 10_000_000 and float_shares > 0:
        score = 78.0
        reasons.append(f"Float محدود ≈ {float_shares/1_000_000:.1f}M")
    elif float_shares <= 25_000_000 and float_shares > 0:
        score = 62.0
    elif float_shares > 50_000_000:
        score = 28.0

    if short_float >= 25:
        score += 14.0
        reasons.append(f"Short float مرتفع ≈ {short_float:.1f}%")
    elif short_float >= 15:
        score += 8.0
        reasons.append(f"Short float ≈ {short_float:.1f}%")
    return _clamp(score), reasons


def score_catalyst_impact(
    cluster: dict[str, Any],
    stock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank the potential market impact of a verified/primary catalyst.

    The score is a research ranking, not a probability or a promise that a
    price explosion will occur.
    """
    stock = stock or {}
    category = str(
        cluster.get("category_normalized")
        or cluster.get("category")
        or "UNCLASSIFIED"
    ).upper()
    bias = str(cluster.get("directional_bias") or "neutral").lower()
    source_rank = _number(cluster.get("source_rank"), 0.0)
    if source_rank <= 0:
        tier = str(cluster.get("source_tier") or "")
        source_rank = {
            "A_OFFICIAL": 100.0,
            "B_ISSUER_PRIMARY": 86.0,
            "B_OFFICIAL_REGISTRY": 88.0,
            "C_CONFIRMATION": 74.0,
            "C_AGGREGATOR": 58.0,
            "D_ATTENTION": 34.0,
        }.get(tier, 48.0)

    quality = _number(cluster.get("catalyst_quality"))
    materiality = _number(cluster.get("materiality"))
    event_potency = _EVENT_POTENCY.get(category, max(35.0, materiality))
    age_days = _number(cluster.get("age_days"), 99.0)
    freshness = _freshness(age_days)

    rvol = max(
        _number(stock.get("finviz_relative_volume")),
        _number(stock.get("relative_volume")),
        _number(stock.get("rvol")),
    )
    participation = _clamp(20.0 + rvol * 22.0)
    breakout_pressure = _number(stock.get("breakout_pressure_score"), 0.0)
    if breakout_pressure <= 0:
        breakout_pressure = 45.0

    supply, supply_reasons = _supply_amplification(stock)
    reaction = str(cluster.get("reaction_state") or "UNKNOWN").upper()
    earlyness = {
        "NOT_YET_REPRICED": 100.0,
        "UNKNOWN": 55.0,
        "REPRICING": 72.0,
        "FAILED_REACTION": 30.0,
        "EXTENDED_CHASING_RISK": 10.0,
    }.get(reaction, 45.0)

    score = (
        source_rank * 0.15
        + quality * 0.16
        + materiality * 0.14
        + event_potency * 0.18
        + freshness * 0.10
        + participation * 0.10
        + breakout_pressure * 0.08
        + supply * 0.05
        + earlyness * 0.04
    )

    drivers: list[str] = []
    risks: list[str] = []
    if source_rank >= 90:
        drivers.append("المصدر رسمي/عالي الاعتمادية")
    elif bool(cluster.get("issuer_primary")):
        drivers.append("الخبر صادر من الشركة مباشرة")
    if event_potency >= 88:
        drivers.append(f"نوع الحدث عالي الحساسية: {category}")
    if freshness >= 90:
        drivers.append("الخبر حديث جدًا")
    if rvol >= 2.0:
        drivers.append(f"RVOL مرتفع {rvol:.2f}×")
    if breakout_pressure >= 70:
        drivers.append(f"ضغط اختراق {breakout_pressure:.0f}/100")
    drivers.extend(supply_reasons[:2])
    if reaction == "NOT_YET_REPRICED":
        drivers.append("السعر لم يُظهر إعادة تسعير كاملة بعد")
    elif reaction == "REPRICING":
        drivers.append("إعادة التسعير بدأت بالفعل")

    dilution = _number(cluster.get("dilution_risk"))
    if dilution >= 70 and bias == "bullish":
        score -= 18.0
        risks.append(f"مخاطر Dilution مرتفعة {dilution:.0f}/100 وتعاكس السيناريو الصاعد")
    elif dilution >= 70 and bias == "bearish":
        drivers.append(f"ضغط تمويلي/Dilution {dilution:.0f}/100 يدعم حساسية الهبوط")

    gap = abs(_number(stock.get("gap_pct")))
    if gap >= 15:
        score -= 12.0
        risks.append(f"Gap كبير {gap:.1f}%؛ خطر مطاردة الحركة")
    if reaction == "EXTENDED_CHASING_RISK":
        score -= 18.0
        risks.append("الحركة ممتدة وقد يكون جزء كبير من الخبر مسعّرًا")
    if reaction == "FAILED_REACTION":
        score -= 15.0
        risks.append("رد فعل السوق الحالي لا يؤكد اتجاه المحفز")

    avg_dollar_volume = _number(stock.get("avg_dollar_volume"))
    if 0 < avg_dollar_volume < 3_000_000:
        score -= 10.0
        risks.append("السيولة الدولارية ضعيفة وقد ترفع مخاطر الانزلاق")

    score = _clamp(score)
    if score >= 85:
        label = "EXTREME"
        label_ar = "محفز شديد القوة"
    elif score >= 75:
        label = "HIGH"
        label_ar = "محفز قوي"
    elif score >= 60:
        label = "BUILDING"
        label_ar = "محفز متوسط/يتطور"
    else:
        label = "LOW"
        label_ar = "محفز ضعيف أو غير مكتمل"

    return {
        "version": "CATALYST_IMPACT_V1",
        "score": round(score, 1),
        "label": label,
        "label_ar": label_ar,
        "directional_bias": bias,
        "category": category,
        "components": {
            "source_reliability": round(source_rank, 1),
            "catalyst_quality": round(quality, 1),
            "materiality": round(materiality, 1),
            "event_potency": round(event_potency, 1),
            "freshness": round(freshness, 1),
            "market_participation": round(participation, 1),
            "breakout_pressure": round(breakout_pressure, 1),
            "supply_amplification": round(supply, 1),
            "earlyness": round(earlyness, 1),
        },
        "market_factors": {
            "rvol": round(rvol, 4),
            "gap_pct": round(gap, 4),
            "short_float_pct": round(
                _pct(
                    stock.get("short_float_pct")
                    if stock.get("short_float_pct") is not None
                    else stock.get("short_float")
                ),
                4,
            ),
            "finviz_style_rvol": stock.get("finviz_relative_volume"),
        },
        "drivers_ar": drivers[:8],
        "risks_ar": risks[:6],
        "score_is_probability": False,
        "guaranteed_explosion": False,
    }
