from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _price(targets: dict[str, Any], key: str) -> float | None:
    value = targets.get(key)
    return _value(value.get("price")) if isinstance(value, dict) else None


def chart_risk_context(
    stock: dict[str, Any],
    side: str,
    targets: dict[str, Any],
) -> dict[str, Any]:
    """Read existing underlying-only chart features without changing CALL/PUT."""
    normalized_side = str(side or "").upper()
    direction = str(stock.get("technical_direction") or "").lower()
    aligned = (normalized_side == "CALL" and direction == "bullish") or (
        normalized_side == "PUT" and direction == "bearish"
    )
    conflict = direction in {"bullish", "bearish"} and not aligned
    spot = _value(stock.get("price"))
    if spot is None or spot <= 0:
        spot = None
    invalidation = _price(targets, "invalidation")
    target_1 = _price(targets, "t1")
    rvol = _value(stock.get("finviz_relative_volume"))
    if rvol is None:
        rvol = _value(stock.get("relative_volume"))
    rsi = _value(stock.get("rsi"))
    pressure = _value(stock.get("breakout_pressure_score"))
    setup_status = str(stock.get("setup_status") or "").lower()

    invalidated = bool(
        spot is not None
        and invalidation is not None
        and invalidation > 0
        and (
            (normalized_side == "CALL" and spot <= invalidation)
            or (normalized_side == "PUT" and spot >= invalidation)
        )
    )
    overextended = setup_status == "too_late"
    if invalidated:
        state = "INVALIDATED_BY_UNDERLYING"
        label = "كسر مستوى الإبطال في السهم"
    elif conflict:
        state = "DIRECTION_CONFLICT"
        label = "اتجاه الشارت يعاكس العقد"
    elif overextended:
        state = "EXTENDED"
        label = "السعر متأخر عن منطقة الدخول"
    elif aligned and pressure is not None and pressure >= 70:
        state = "ALIGNED_PRESSURE"
        label = "الاتجاه متوافق وضغط الاختراق مرتفع"
    elif aligned:
        state = "ALIGNED"
        label = "الاتجاه الفني متوافق مع العقد"
    else:
        state = "UNCONFIRMED"
        label = "مؤشرات الاتجاه غير مكتملة"

    return {
        "state": state,
        "label_ar": label,
        "direction": direction or "unknown",
        "direction_conflict": conflict,
        "spot": spot,
        "target_1": target_1,
        "invalidation": invalidation,
        "rvol": rvol,
        "rsi": rsi,
        "breakout_pressure_score": pressure,
        "relative_strength_20d": _value(stock.get("relative_strength_20d")),
        "trigger_type": stock.get("trigger_type"),
        "market_regime": stock.get("market_regime"),
        "underlying_price_timestamp": stock.get("quote_timestamp")
        or stock.get("price_timestamp"),
        "research_only": True,
        "note_ar": "مؤشرات السهم من آخر دورة فحص؛ لا تُعد إثباتًا لسعر لحظي.",
    }


def catalyst_report_ar(
    symbol: str,
    catalyst: dict[str, Any],
    stock: dict[str, Any],
    chart: dict[str, Any],
) -> dict[str, Any]:
    """Explain verified news vs watch-only attention in Arabic."""
    impact = catalyst.get("explosion_impact")
    impact = impact if isinstance(impact, dict) else {}
    headline = str(catalyst.get("headline") or "").strip()
    source = str(catalyst.get("primary_source") or "").strip()
    primary_url = str(catalyst.get("primary_url") or "").strip()
    if not primary_url.startswith(("https://", "http://")):
        primary_url = ""
    official = catalyst.get("official_confirmed") is True
    issuer = catalyst.get("issuer_primary") is True
    verified = "OFFICIAL" if official else "ISSUER" if issuer else "UNVERIFIED"
    proof_ar = (
        "خبر مثبت من جهة رسمية"
        if official
        else "بيان صادر من الشركة؛ المطابقة الرسمية مطلوبة"
        if issuer
        else "السبب غير مثبت رسميًا؛ اهتمام أو خبر ثانوي فقط"
    )
    score = _value(impact.get("score")) if verified != "UNVERIFIED" else None
    drivers = impact.get("drivers_ar") if isinstance(impact.get("drivers_ar"), list) else []
    risks = impact.get("risks_ar") if isinstance(impact.get("risks_ar"), list) else []
    reasons = [str(x) for x in drivers[:3] if str(x).strip()]
    warnings = [str(x) for x in risks[:2] if str(x).strip()]
    if not official:
        warnings.insert(0, "المحفز ليس إفصاحًا رسميًا مؤكدًا")
    if chart.get("direction_conflict"):
        warnings.append("اتجاه الشارت الحالي يعارض اتجاه العقد")
    if not headline:
        headline = "لا يوجد خبر موثّق جديد مرتبط بالعقد"
    score_text = f"{score:.0f}/100" if score is not None else "غير مؤهل للتقييم الرسمي"
    report = (
        f"{symbol}: {proof_ar}. الخبر: {headline}. "
        f"المصدر: {source or 'غير معروف'}. "
        f"تقييم أثر المحفز: {score_text} (تصنيف بحثي وليس احتمال ربح). "
        f"شارت السهم: {chart.get('label_ar', 'غير معروف')}."
    )
    if reasons:
        report += " عوامل داعمة: " + "؛ ".join(reasons) + "."
    if warnings:
        report += " المخاطر: " + "؛ ".join(warnings) + "."
    return {
        "verification": verified,
        "official_confirmed": official,
        "headline": headline,
        "primary_source": source,
        "primary_url": primary_url,
        "category": catalyst.get("category_normalized") or catalyst.get("category"),
        "event_date": catalyst.get("event_date"),
        "impact_score": score,
        "impact_is_probability": False,
        "drivers_ar": reasons,
        "risks_ar": warnings,
        "proof_ar": proof_ar,
        "finviz_style_context": {
            "rvol": chart.get("rvol"),
            "breakout_pressure": chart.get("breakout_pressure_score"),
            "gap_pct": _value(stock.get("gap_pct")),
            "distance_52w_high": _value(stock.get("distance_52w_high")),
            "short_float_pct": _value(stock.get("short_float_pct")),
        },
        "report_ar": report,
        "research_only": True,
    }


def record_option_quote_snapshot(
    history: Any,
    row: dict[str, Any],
    *,
    now: datetime,
    max_age_minutes: float,
    max_snapshots: int = 240,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a free, self-collected quote history from genuine provider stamps.

    This is not a vendor historical feed. No timestamp -> no snapshot. A
    generated-at timestamp is never used as the market-data timestamp.
    Only fresh, valid, two-sided quotes enter this research history.
    """
    entries = [dict(item) for item in history if isinstance(item, dict)] if isinstance(history, list) else []
    raw = row.get("quote_timestamp")
    if not raw and str(row.get("timestamp_kind") or "").lower() in {
        "quote", "provider_quote", "quote_snapshot"
    }:
        raw = row.get("updated_at")
    quote_time = _utc(raw)
    if quote_time is None:
        return entries[-max_snapshots:], {"recorded": False, "reason": "missing_provider_quote_time"}
    age = (now - quote_time).total_seconds() / 60.0
    if age < -2.0 or age > max_age_minutes:
        return entries[-max_snapshots:], {"recorded": False, "reason": "stale_or_future_quote"}

    bid = _value(row.get("bid"))
    ask = _value(row.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return entries[-max_snapshots:], {"recorded": False, "reason": "invalid_bid_ask"}
    source = str(row.get("source") or "").strip()
    if not source:
        return entries[-max_snapshots:], {"recorded": False, "reason": "missing_source"}

    timestamp = quote_time.isoformat()
    # Exactly one observation per provider+timestamp; repeated workflow
    # runs cannot manufacture a higher-frequency historical tape.
    key = (source.lower(), timestamp)
    if any(
        (str(entry.get("source") or "").lower(), str(entry.get("quote_timestamp") or "")) == key
        for entry in entries
    ):
        return entries[-max_snapshots:], {"recorded": False, "reason": "duplicate_provider_snapshot"}

    entry = {
        "quote_timestamp": timestamp,
        "collected_at": now.isoformat(),
        "source": source,
        "source_family": row.get("source_family"),
        "bid": round(bid, 6),
        "ask": round(ask, 6),
        "mid": round((bid + ask) / 2, 6),
        "mark_for_exit": round(bid, 6),
        "iv": _value(row.get("iv")),
        "underlying_price": _value(row.get("underlying_price")),
        "data_status": "RESEARCH_QUOTE",
        "execution_grade": False,
    }
    entries.append(entry)
    entries.sort(key=lambda x: str(x.get("quote_timestamp") or ""))
    entries = entries[-max_snapshots:]
    return entries, {"recorded": True, "reason": "new_provider_snapshot", "count": len(entries)}
