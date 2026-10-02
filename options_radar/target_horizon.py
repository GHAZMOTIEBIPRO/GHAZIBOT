from __future__ import annotations

import math
from typing import Any

from .omega_target_learning import target_probability


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def estimate_target_horizon(
    stock: dict[str, Any],
    target_map: dict[str, Any] | None,
    *,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        calibrated = target_probability(
            calibration,
            target=label.upper(),
            horizon_bucket=bucket,
        )
        target_row = {
            "target": label.upper(),
            "price": target,
            "distance_pct": round(distance / price * 100.0, 2),
            "atr_distance": round(atr_distance, 2) if atr > 0 else None,
            "horizon_bucket": bucket,
            "estimated_time_ar": sessions,
            "probability_status": "CALIBRATED" if calibrated else "INSUFFICIENT_SAMPLE",
            "historical_hit_rate": None,
            "historical_hit_rate_pct": None,
            "historical_sample": 0,
            "historical_ci95_pct": None,
            "historical_median_sessions_to_hit": None,
        }
        if calibrated:
            rate = calibrated.get("historical_hit_rate")
            low = calibrated.get("ci95_low")
            high = calibrated.get("ci95_high")
            target_row.update(
                {
                    "historical_hit_rate": rate,
                    "historical_hit_rate_pct": round(float(rate) * 100.0, 1) if rate is not None else None,
                    "historical_sample": int(calibrated.get("historical_sample") or 0),
                    "historical_ci95_pct": (
                        [round(float(low) * 100.0, 1), round(float(high) * 100.0, 1)]
                        if low is not None and high is not None
                        else None
                    ),
                    "historical_median_sessions_to_hit": calibrated.get("median_sessions_to_hit"),
                    "historical_median_elapsed_hours_to_hit": calibrated.get("median_elapsed_hours_to_hit"),
                }
            )
            if calibrated.get("median_sessions_to_hit") is not None:
                target_row["estimated_time_ar"] = (
                    f"وسيط تاريخي {float(calibrated['median_sessions_to_hit']):g} جلسة"
                    f"؛ التقدير البنيوي: {sessions}"
                )
        targets.append(target_row)

    alignment = "UNKNOWN"
    if side == "call" and regime in {"bullish", "up", "uptrend"}:
        alignment = "ALIGNED"
    elif side == "put" and regime in {"bearish", "down", "downtrend"}:
        alignment = "ALIGNED"
    elif regime:
        alignment = "MIXED"

    primary = targets[0] if targets else {}
    calibrated_targets = sum(row.get("probability_status") == "CALIBRATED" for row in targets)
    return {
        "method": "ATR_DISTANCE_TIME_BUCKET_V2_WITH_GATED_CALIBRATION",
        "is_probability": bool(primary.get("probability_status") == "CALIBRATED"),
        "is_guarantee": False,
        "calibrated_target_count": calibrated_targets,
        "calibration_status": (
            "CALIBRATED"
            if calibrated_targets
            else "INSUFFICIENT_SAMPLE"
        ),
        "primary_horizon": primary.get("horizon_bucket", "UNKNOWN"),
        "primary_time_ar": primary.get("estimated_time_ar", "غير محدد"),
        "timeframe_alignment": alignment,
        "targets": targets,
    }
