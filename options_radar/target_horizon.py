from __future__ import annotations

import math
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def estimate_target_horizon(stock: dict[str, Any], target_map: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate a research horizon from target distance, ATR and setup regime.

    This is deliberately a time bucket, not a promised arrival time. It lets the
    option selector match DTE to the underlying thesis instead of choosing expiry
    from catalyst strength alone.
    """
    target_map = target_map or {}
    price = _num(stock.get("price"))
    atr = _num(stock.get("atr") or stock.get("atr14"))
    side = str(stock.get("setup_side") or "").lower()
    rvol = max(_num(stock.get("relative_volume")), _num(stock.get("finviz_relative_volume")))
    regime = str(stock.get("timeframe_regime") or stock.get("technical_direction") or "").lower()
    targets: list[dict[str, Any]] = []

    for label in ("t1", "t2", "t3"):
        row = target_map.get(label) if isinstance(target_map.get(label), dict) else {}
        target = _num(row.get("price"))
        if price <= 0 or target <= 0:
            continue
        distance = abs(target - price)
        atr_distance = distance / atr if atr > 0 else 0.0
        if atr_distance <= 1.0:
            bucket, sessions = "INTRADAY_1D", "نفس الجلسة إلى جلسة"
        elif atr_distance <= 2.0:
            bucket, sessions = "SHORT_1_3D", "1–3 جلسات"
        elif atr_distance <= 3.5:
            bucket, sessions = "SWING_3_7D", "3–7 جلسات"
        else:
            bucket, sessions = "POSITION_1_4W", "1–4 أسابيع"
        if rvol >= 2.0 and bucket in {"SHORT_1_3D", "SWING_3_7D"}:
            sessions += "؛ RVOL مرتفع وقد يسرّع الحركة"
        targets.append({
            "target": label.upper(),
            "price": target,
            "distance_pct": round(distance / price * 100.0, 2),
            "atr_distance": round(atr_distance, 2) if atr > 0 else None,
            "horizon_bucket": bucket,
            "estimated_time_ar": sessions,
        })

    alignment = "UNKNOWN"
    if side == "call" and regime in {"bullish", "up", "uptrend"}:
        alignment = "ALIGNED"
    elif side == "put" and regime in {"bearish", "down", "downtrend"}:
        alignment = "ALIGNED"
    elif regime:
        alignment = "MIXED"

    primary = targets[0] if targets else {}
    return {
        "method": "ATR_DISTANCE_TIME_BUCKET_V1",
        "is_probability": False,
        "is_guarantee": False,
        "primary_horizon": primary.get("horizon_bucket", "UNKNOWN"),
        "primary_time_ar": primary.get("estimated_time_ar", "غير محدد"),
        "timeframe_alignment": alignment,
        "targets": targets,
    }
