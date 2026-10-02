from __future__ import annotations

import math
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pct(value: Any) -> float:
    number = _number(value)
    if 0 < number <= 1:
        number *= 100.0
    return max(0.0, number)


def _social_score(stock: dict[str, Any]) -> float:
    evidence = stock.get("external_evidence") if isinstance(stock.get("external_evidence"), dict) else {}
    return max(
        _number(stock.get("social_score")),
        _number(evidence.get("social_score")),
        _number(stock.get("social_acceleration_score")),
        _number(evidence.get("social_acceleration_score")),
    )


def _short_float_pct(stock: dict[str, Any]) -> float:
    return _pct(stock.get("short_float") if stock.get("short_float") is not None else stock.get("short_float_pct"))


def _float_shares(stock: dict[str, Any]) -> float:
    for key in ("effective_float", "effective_float_shares", "public_float_shares", "float_shares", "float"):
        value = _number(stock.get(key))
        if value > 0:
            return value
    return 0.0


def _corporate_event_score(cluster: dict[str, Any]) -> float:
    text = " ".join(
        str(cluster.get(key) or "")
        for key in ("event_type", "catalyst_type", "headline", "summary", "form")
    ).lower()
    if not text.strip():
        return 0.0

    strong = (
        "merger",
        "acquisition",
        "tender offer",
        "strategic alternative",
        "definitive agreement",
        "fda approval",
        "fda clearance",
        "clinical trial",
        "bankruptcy",
        "restructuring",
        "reverse split",
        "spin-off",
        "spinoff",
    )
    medium = (
        "8-k",
        "6-k",
        "13d",
        "contract award",
        "partnership",
        "licensing",
        "guidance",
        "earnings",
    )
    if any(token in text for token in strong):
        return 95.0
    if any(token in text for token in medium):
        return 72.0
    return 35.0


def _price_lag_score(stock: dict[str, Any], cluster: dict[str, Any]) -> float:
    day = abs(_number(stock.get("performance_day") or stock.get("change_pct")))
    distance = abs(_number(stock.get("distance_to_trigger_atr")))
    state = str(stock.get("entry_state") or stock.get("setup_status") or "").lower()
    reaction = str(cluster.get("reaction_state") or "").upper()

    score = 50.0
    if day <= 3:
        score += 28.0
    elif day <= 8:
        score += 18.0
    elif day <= 15:
        score += 7.0
    elif day >= 35:
        score -= 35.0

    if distance <= 0.5:
        score += 10.0
    elif distance >= 2.0:
        score -= 18.0

    if state in {"early", "forming", "watch", "waiting"}:
        score += 12.0
    elif state in {"too_late", "extended"}:
        score -= 35.0

    if reaction == "NOT_YET_REPRICED":
        score += 18.0
    elif reaction == "EXTENDED_CHASING_RISK":
        score -= 40.0
    return max(0.0, min(100.0, score))


def classify_explosion_cause(
    stock: dict[str, Any],
    cluster: dict[str, Any] | None,
    dimensions: dict[str, Any],
) -> dict[str, Any]:
    """Explain *why* a setup is explosive without claiming legal/economic causation."""
    cluster = cluster if isinstance(cluster, dict) else {}
    supply = _number(dimensions.get("supply_structure"))
    participation = _number(dimensions.get("participation"))
    price = _number(dimensions.get("price_structure"))
    catalyst = _number(dimensions.get("catalyst"))
    short_float = _short_float_pct(stock)
    social = min(100.0, _social_score(stock))
    corporate = _corporate_event_score(cluster)
    price_lag = _price_lag_score(stock, cluster)

    scores = {
        "SUPPLY_VACUUM": max(0.0, min(100.0, supply * 0.72 + participation * 0.18 + price_lag * 0.10)),
        "CATALYST_REPRICING": max(0.0, min(100.0, catalyst * 0.62 + price_lag * 0.23 + participation * 0.15)),
        "SHORT_SQUEEZE": max(
            0.0,
            min(100.0, min(100.0, short_float * 3.0) * 0.50 + supply * 0.20 + participation * 0.30),
        ),
        "MOMENTUM_IGNITION": max(0.0, min(100.0, participation * 0.48 + price * 0.37 + price_lag * 0.15)),
        "CORPORATE_EVENT": max(0.0, min(100.0, corporate * 0.50 + catalyst * 0.35 + price_lag * 0.15)),
        # Social is deliberately secondary: it can strengthen discovery but may
        # not outrank price/participation/catalyst evidence by itself.
        "SOCIAL_ATTENTION_SHOCK": max(0.0, min(100.0, social * 0.45 + participation * 0.30 + price * 0.25)),
    }

    strong = [name for name, score in scores.items() if score >= 72.0]
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if len(strong) >= 3:
        primary = "MULTI_FACTOR_EXPLOSION"
        primary_score = min(100.0, sum(scores[name] for name in strong) / len(strong) + 5.0)
    else:
        primary, primary_score = ranked[0]

    labels_ar = {
        "SUPPLY_VACUUM": "نقص معروض / Supply Vacuum",
        "CATALYST_REPRICING": "إعادة تسعير محفز",
        "SHORT_SQUEEZE": "ضغط شورت / Squeeze",
        "MOMENTUM_IGNITION": "اشتعال زخم وسيولة",
        "CORPORATE_EVENT": "حدث جوهري للشركة",
        "SOCIAL_ATTENTION_SHOCK": "قفزة انتباه اجتماعي",
        "MULTI_FACTOR_EXPLOSION": "انفجار متعدد العوامل",
    }
    drivers = [
        {"type": name, "label_ar": labels_ar[name], "score": round(score, 1)}
        for name, score in ranked
        if score >= 55.0
    ][:5]

    explanation_bits: list[str] = []
    if supply >= 70:
        explanation_bits.append(f"اختلال العرض {supply:.0f}/100")
    if catalyst >= 70:
        explanation_bits.append(f"قوة المحفز {catalyst:.0f}/100")
    if participation >= 70:
        explanation_bits.append(f"تسارع المشاركة/الحجم {participation:.0f}/100")
    if short_float >= 15:
        explanation_bits.append(f"Short float ≈ {short_float:.1f}%")
    if price_lag >= 70:
        explanation_bits.append("السعر ما زال متأخرًا نسبيًا عن الأدلة")
    if social >= 60:
        explanation_bits.append(f"تسارع اجتماعي {social:.0f}/100")

    return {
        "version": "EXPLOSION_CAUSE_V1",
        "primary": primary,
        "primary_label_ar": labels_ar[primary],
        "primary_score": round(primary_score, 1),
        "drivers": drivers,
        "scores": {key: round(value, 1) for key, value in scores.items()},
        "strong_driver_count": len(strong),
        "price_lag_score": round(price_lag, 1),
        "short_float_pct": round(short_float, 2),
        "social_score": round(social, 1),
        "explanation_ar": " | ".join(explanation_bits) or "لا يوجد سبب منفرد مسيطر؛ الإشارة مركبة وضعيفة التفسير",
        "causation_proven": False,
    }


def manipulation_risk(
    stock: dict[str, Any],
    cluster: dict[str, Any] | None,
    explosion_cause: dict[str, Any],
) -> dict[str, Any]:
    """Research risk flag, never an accusation that manipulation occurred."""
    cluster = cluster if isinstance(cluster, dict) else {}
    float_shares = _float_shares(stock)
    day = abs(_number(stock.get("performance_day") or stock.get("change_pct")))
    week = abs(_number(stock.get("performance_week") or stock.get("week_change_pct")))
    social = _number(explosion_cause.get("social_score"))
    catalyst_quality = _number(cluster.get("catalyst_quality"))
    dilution = _number(cluster.get("dilution_risk"))
    text = " ".join(
        str(cluster.get(key) or "")
        for key in ("event_type", "catalyst_type", "headline", "summary", "form")
    ).lower()

    factors: list[tuple[str, float, str]] = []
    if 0 < float_shares <= 3_000_000:
        factors.append(("micro_float", 24.0, f"Float شديد الانخفاض ≈ {float_shares/1_000_000:.2f}M"))
    elif 0 < float_shares <= 10_000_000:
        factors.append(("low_float", 14.0, f"Float منخفض ≈ {float_shares/1_000_000:.1f}M"))

    if day >= 50:
        factors.append(("extreme_day_move", 22.0, f"حركة يومية شديدة {day:.1f}%"))
    elif day >= 25:
        factors.append(("large_day_move", 12.0, f"حركة يومية كبيرة {day:.1f}%"))
    if week >= 120:
        factors.append(("extreme_week_move", 16.0, f"حركة أسبوعية شديدة {week:.1f}%"))
    if social >= 70:
        factors.append(("social_hype", 14.0, f"نشاط اجتماعي مرتفع {social:.0f}/100"))
    if catalyst_quality < 35 and (day >= 15 or social >= 50):
        factors.append(("weak_verified_cause", 18.0, "الحركة أقوى من المحفز الرسمي المتحقق حاليًا"))
    if dilution >= 70:
        factors.append(("dilution_overhang", 18.0, f"Dilution risk {dilution:.0f}/100"))
    if "reverse split" in text:
        factors.append(("reverse_split_context", 14.0, "يوجد سياق Reverse Split يحتاج حذرًا"))
    if any(token in text for token in ("atm", "at-the-market", "shelf", "s-3", "424b5", "warrant")):
        factors.append(("financing_overhang", 12.0, "يوجد سياق تمويل/إصدار قد يزيد مخاطر الحركة"))

    score = min(100.0, sum(weight for _, weight, _ in factors))
    if score >= 70:
        label = "VERY_HIGH"
        label_ar = "مرتفع جدًا"
    elif score >= 50:
        label = "HIGH"
        label_ar = "مرتفع"
    elif score >= 25:
        label = "MEDIUM"
        label_ar = "متوسط"
    else:
        label = "LOW"
        label_ar = "منخفض"

    return {
        "version": "MANIPULATION_RISK_V1",
        "score": round(score, 1),
        "label": label,
        "label_ar": label_ar,
        "factors": [
            {"code": code, "weight": weight, "reason_ar": reason}
            for code, weight, reason in factors
        ],
        "is_accusation": False,
        "disclaimer_ar": "درجة مخاطر بحثية لخصائص قد ترافق الضخ أو التلاعب؛ لا تثبت وقوع تلاعب.",
    }


def adaptive_dimension_weights(explosion_cause: dict[str, Any]) -> dict[str, float]:
    """Choose weights by setup archetype; risk remains a separate penalty."""
    primary = str(explosion_cause.get("primary") or "MULTI_FACTOR_EXPLOSION")
    table = {
        "SUPPLY_VACUUM": {
            "catalyst": 0.16,
            "participation": 0.28,
            "supply_structure": 0.27,
            "price_structure": 0.21,
            "options_structure": 0.08,
        },
        "CATALYST_REPRICING": {
            "catalyst": 0.32,
            "participation": 0.18,
            "supply_structure": 0.10,
            "price_structure": 0.25,
            "options_structure": 0.15,
        },
        "SHORT_SQUEEZE": {
            "catalyst": 0.10,
            "participation": 0.29,
            "supply_structure": 0.26,
            "price_structure": 0.23,
            "options_structure": 0.12,
        },
        "MOMENTUM_IGNITION": {
            "catalyst": 0.10,
            "participation": 0.29,
            "supply_structure": 0.12,
            "price_structure": 0.34,
            "options_structure": 0.15,
        },
        "CORPORATE_EVENT": {
            "catalyst": 0.35,
            "participation": 0.14,
            "supply_structure": 0.08,
            "price_structure": 0.25,
            "options_structure": 0.18,
        },
        "SOCIAL_ATTENTION_SHOCK": {
            "catalyst": 0.15,
            "participation": 0.25,
            "supply_structure": 0.15,
            "price_structure": 0.30,
            "options_structure": 0.15,
        },
        "MULTI_FACTOR_EXPLOSION": {
            "catalyst": 0.24,
            "participation": 0.21,
            "supply_structure": 0.14,
            "price_structure": 0.25,
            "options_structure": 0.16,
        },
    }
    return table.get(primary, table["MULTI_FACTOR_EXPLOSION"])
