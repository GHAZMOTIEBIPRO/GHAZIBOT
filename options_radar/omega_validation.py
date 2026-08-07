from __future__ import annotations

from typing import Any


def build_validation_status(payload: dict[str, Any], minimum_oos_sample: int = 100) -> dict[str, Any]:
    """Report validation truthfully; rankings are not converted to probabilities."""

    calibration = payload.get("calibration") if isinstance(payload.get("calibration"), dict) else {}
    gate = payload.get("calibration_gate") if isinstance(payload.get("calibration_gate"), dict) else {}
    oos = calibration.get("out_of_sample") if isinstance(calibration.get("out_of_sample"), dict) else {}

    sample = int(
        oos.get(
            "sample",
            gate.get(
                "matured_sample",
                calibration.get("matured_sample", calibration.get("priced_sample", 0)),
            ),
        )
        or 0
    )
    explicit_oos = bool(oos.get("validated") is True and oos.get("time_split") is True)
    has_metrics = all(key in oos for key in ("hit_rate", "expectancy", "drawdown"))
    sufficient = sample >= minimum_oos_sample

    if explicit_oos and has_metrics and sufficient:
        oos_status = "VALIDATED_OOS_DATASET"
        edge_status = "OOS VALIDATION AVAILABLE — REVIEW METRICS"
    elif sample:
        oos_status = "INSUFFICIENT_OR_NOT_TIME_SPLIT"
        edge_status = "EDGE NOT YET PROVEN"
    else:
        oos_status = "NOT_RUN"
        edge_status = "EDGE NOT YET PROVEN"

    return {
        "oos_status": oos_status,
        "edge_status": edge_status,
        "sample": sample,
        "minimum_sample": minimum_oos_sample,
        "time_split_confirmed": bool(oos.get("time_split")),
        "probabilities_calibrated": False,
        "automatic_weight_changes": False,
        "requirements": [
            "Chronological train/validation split",
            "No look-ahead leakage",
            "Independent matured outcomes",
            f"At least {minimum_oos_sample} OOS observations",
            "Report expectancy, drawdown and hit-rate with uncertainty",
        ],
    }
