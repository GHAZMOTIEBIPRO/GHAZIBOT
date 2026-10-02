from __future__ import annotations

import math
from typing import Any, Callable, Iterable


MIN_FACTOR_SAMPLE = 20
MIN_EXCESS_FAILURE_RATE = 0.08
MAX_STOCK_FAILURE_PENALTY = 3.0
MAX_OPTIONS_FAILURE_PENALTY = 4.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def option_failure_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    dte = _number(row.get("dte"), 999.0)
    spread = _number(row.get("spread_pct"))
    iv = _number(row.get("iv"))
    delta = abs(_number(row.get("delta")))
    vol_oi = _number(row.get("vol_oi") or row.get("vol_to_oi_ratio"))
    side = str(row.get("option_type") or "").lower()
    regime = str(row.get("market_regime") or "").lower()

    if dte <= 2:
        flags.append("VERY_SHORT_DTE")
    elif dte <= 7:
        flags.append("SHORT_DTE")
    if spread >= 0.15:
        flags.append("VERY_WIDE_SPREAD")
    elif spread >= 0.10:
        flags.append("WIDE_SPREAD")
    if iv >= 1.5:
        flags.append("EXTREME_IV")
    elif iv >= 1.0:
        flags.append("HIGH_IV")
    if 0 < delta < 0.25:
        flags.append("LOW_DELTA")
    if 0 < vol_oi < 0.50:
        flags.append("LOW_RELATIVE_ACTIVITY")
    if side == "call" and regime in {"risk_off", "bearish"}:
        flags.append("REGIME_SIDE_CONFLICT")
    elif side == "put" and regime in {"risk_on", "bullish"}:
        flags.append("REGIME_SIDE_CONFLICT")
    return flags


def stock_failure_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    stage = str(row.get("entry_stage") or row.get("stage") or "").upper()
    score = _number(row.get("entry_score", row.get("score")))
    regime = str(row.get("market_regime") or "").lower()
    evidence = str(row.get("entry_evidence_state") or "").upper()
    cause_tier = str(row.get("cause_tier") or "").upper()

    if stage in {"WATCH", "PRESSURE_BUILDING"}:
        flags.append("EARLY_UNCONFIRMED_STAGE")
    if stage == "EXTENDED":
        flags.append("EXTENDED_ENTRY")
    if score and score < 72:
        flags.append("LOW_ENTRY_SCORE")
    if not regime or regime == "unknown":
        flags.append("UNKNOWN_REGIME")
    if (
        "NO_PRIMARY" in evidence
        or evidence in {"LEGACY_UNKNOWN", "UNKNOWN", ""}
        or cause_tier in {"", "UNKNOWN", "NONE"}
    ):
        flags.append("WEAK_CAUSE_EVIDENCE")
    return flags


def build_failure_factor_stats(
    rows: Iterable[dict[str, Any]],
    flag_fn: Callable[[dict[str, Any]], list[str]],
    *,
    minimum_sample: int = MIN_FACTOR_SAMPLE,
    max_penalty: float = 4.0,
) -> dict[str, Any]:
    decisive = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("terminal_outcome") in {"success", "failed"}
    ]
    baseline_failures = sum(row.get("terminal_outcome") == "failed" for row in decisive)
    baseline = baseline_failures / len(decisive) if decisive else None

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in decisive:
        for flag in set(flag_fn(row)):
            grouped.setdefault(flag, []).append(row)

    factors: dict[str, dict[str, Any]] = {}
    for flag, group in sorted(grouped.items()):
        sample = len(group)
        failures = sum(row.get("terminal_outcome") == "failed" for row in group)
        failure_rate = failures / sample if sample else 0.0
        excess = failure_rate - baseline if baseline is not None else 0.0
        eligible = sample >= minimum_sample
        harmful = eligible and excess >= MIN_EXCESS_FAILURE_RATE
        penalty = (
            min(max_penalty, max(0.0, excess) * 10.0)
            if harmful
            else 0.0
        )
        factors[flag] = {
            "sample": sample,
            "failures": failures,
            "successes": sample - failures,
            "failure_rate": round(failure_rate, 4),
            "baseline_failure_rate": round(baseline, 4) if baseline is not None else None,
            "excess_failure_rate": round(excess, 4),
            "eligible": eligible,
            "harmful_association": harmful,
            "score_penalty": round(penalty, 2),
        }

    return {
        "decisive_sample": len(decisive),
        "baseline_failure_rate": round(baseline, 4) if baseline is not None else None,
        "minimum_factor_sample": minimum_sample,
        "minimum_excess_failure_rate": MIN_EXCESS_FAILURE_RATE,
        "factors": factors,
        "policy": {
            "association_not_causation": True,
            "no_penalty_below_minimum_sample": True,
            "only_excess_failure_generates_penalty": True,
        },
    }


def failure_factor_penalty(
    evidence: dict[str, Any] | None,
    row: dict[str, Any],
    *,
    domain: str,
) -> tuple[float, list[str]]:
    model = evidence if isinstance(evidence, dict) else {}
    factors = model.get("factors") if isinstance(model.get("factors"), dict) else {}
    flag_fn = option_failure_flags if domain == "options" else stock_failure_flags
    cap = MAX_OPTIONS_FAILURE_PENALTY if domain == "options" else MAX_STOCK_FAILURE_PENALTY

    penalty = 0.0
    applied: list[str] = []
    for flag in flag_fn(row):
        evidence_row = factors.get(flag) if isinstance(factors.get(flag), dict) else {}
        if evidence_row.get("harmful_association") is not True:
            continue
        value = _number(evidence_row.get("score_penalty"))
        if value <= 0:
            continue
        penalty += value
        applied.append(flag)
    return round(min(cap, penalty), 2), applied
