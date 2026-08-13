from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

STOCK_MIN_MATURED = 60
STOCK_MIN_COHORT = 20
OPTIONS_MIN_DECISIVE = 100
OPTIONS_MIN_COHORT = 20
MAX_STOCK_ADJUSTMENT = 8.0
MAX_OPTIONS_ADJUSTMENT = 6.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _load(path: str | Path, default: Any) -> Any:
    source = Path(path)
    if not source.exists():
        return default
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    output: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            output.append(row)
    return output


def score_band(score: Any) -> str:
    value = _number(score)
    if value >= 90:
        return "90-100"
    if value >= 80:
        return "80-89"
    if value >= 72:
        return "72-79"
    if value >= 65:
        return "65-71"
    return "below-65"


def _rate_adjustment(rate: float, baseline: float, *, scale: float, cap: float) -> float:
    delta = rate - baseline
    if abs(delta) < 0.08:
        return 0.0
    return round(max(-cap, min(cap, delta * scale)), 2)


def _stock_records(stock_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (stock_state.get("signals") or {}).values() if isinstance(row, dict)]
    return [
        row
        for row in rows
        if isinstance(row.get("checkpoints"), dict)
        and "60m" in row["checkpoints"]
        and row.get("terminal_outcome") in {"success", "failed"}
    ]


def _options_records(signals: list[dict[str, Any]], outcomes: dict[str, Any]) -> list[dict[str, Any]]:
    states = outcomes.get("signals") if isinstance(outcomes, dict) else {}
    states = states if isinstance(states, dict) else {}
    output: list[dict[str, Any]] = []
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "")
        state = states.get(signal_id)
        if not isinstance(state, dict):
            continue
        checkpoints = state.get("checkpoints") if isinstance(state.get("checkpoints"), dict) else {}
        terminal = str(state.get("terminal_outcome") or "open")
        if "1d" not in checkpoints or terminal not in {"success", "failed"}:
            continue
        output.append({**signal, "terminal_outcome": terminal})
    return output


def _cohort_stats(
    rows: Iterable[dict[str, Any]],
    key_fn,
    *,
    baseline: float,
    minimum: int,
    scale: float,
    cap: float,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(key_fn(row) or "unknown")
        groups.setdefault(key, []).append(row)
    output: dict[str, dict[str, Any]] = {}
    for key, group in groups.items():
        decisive = [row for row in group if row.get("terminal_outcome") in {"success", "failed"}]
        successes = sum(row.get("terminal_outcome") == "success" for row in decisive)
        count = len(decisive)
        rate = successes / count if count else 0.0
        eligible = count >= minimum
        output[key] = {
            "sample": count,
            "successes": successes,
            "failures": count - successes,
            "success_rate": round(rate, 4) if count else None,
            "eligible": eligible,
            "score_adjustment": _rate_adjustment(rate, baseline, scale=scale, cap=cap) if eligible else 0.0,
        }
    return output


def build_learning_model(
    *,
    stock_outcomes_path: str | Path,
    options_signals_path: str | Path,
    options_outcomes_path: str | Path,
) -> dict[str, Any]:
    stock_state = _load(stock_outcomes_path, {"signals": {}})
    options_signals = _load_jsonl(options_signals_path)
    options_outcomes = _load(options_outcomes_path, {"signals": {}})

    stock_rows = _stock_records(stock_state if isinstance(stock_state, dict) else {})
    option_rows = _options_records(options_signals, options_outcomes if isinstance(options_outcomes, dict) else {})

    stock_success = sum(row.get("terminal_outcome") == "success" for row in stock_rows)
    stock_baseline = stock_success / len(stock_rows) if stock_rows else 0.5
    stock_ready = len(stock_rows) >= STOCK_MIN_MATURED

    option_success = sum(row.get("terminal_outcome") == "success" for row in option_rows)
    option_baseline = option_success / len(option_rows) if option_rows else 0.5
    options_ready = len(option_rows) >= OPTIONS_MIN_DECISIVE

    stock = {
        "ready": stock_ready,
        "matured_decisive": len(stock_rows),
        "minimum_required": STOCK_MIN_MATURED,
        "baseline_success_rate": round(stock_baseline, 4) if stock_rows else None,
        "score_bands": _cohort_stats(
            stock_rows,
            lambda row: row.get("score_band") or score_band(row.get("score")),
            baseline=stock_baseline,
            minimum=STOCK_MIN_COHORT,
            scale=18.0,
            cap=5.0,
        ),
        "stages": _cohort_stats(
            stock_rows,
            lambda row: row.get("stage"),
            baseline=stock_baseline,
            minimum=STOCK_MIN_COHORT,
            scale=12.0,
            cap=3.0,
        ),
        "regimes": _cohort_stats(
            stock_rows,
            lambda row: row.get("market_regime"),
            baseline=stock_baseline,
            minimum=STOCK_MIN_COHORT,
            scale=10.0,
            cap=2.0,
        ),
        "cause_tiers": _cohort_stats(
            stock_rows,
            lambda row: row.get("cause_tier"),
            baseline=stock_baseline,
            minimum=15,
            scale=10.0,
            cap=2.0,
        ),
    }

    options = {
        "ready": options_ready,
        "matured_decisive": len(option_rows),
        "minimum_required": OPTIONS_MIN_DECISIVE,
        "baseline_success_rate": round(option_baseline, 4) if option_rows else None,
        "score_bands": _cohort_stats(
            option_rows,
            lambda row: score_band(row.get("score")),
            baseline=option_baseline,
            minimum=OPTIONS_MIN_COHORT,
            scale=16.0,
            cap=4.0,
        ),
        "regimes": _cohort_stats(
            option_rows,
            lambda row: row.get("market_regime"),
            baseline=option_baseline,
            minimum=OPTIONS_MIN_COHORT,
            scale=10.0,
            cap=2.0,
        ),
        "sides": _cohort_stats(
            option_rows,
            lambda row: str(row.get("option_type") or "").lower(),
            baseline=option_baseline,
            minimum=OPTIONS_MIN_COHORT,
            scale=8.0,
            cap=1.5,
        ),
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "no_live_weight_change_before_minimum_sample": True,
            "stock_min_matured": STOCK_MIN_MATURED,
            "options_min_decisive": OPTIONS_MIN_DECISIVE,
            "stock_adjustment_cap": MAX_STOCK_ADJUSTMENT,
            "options_adjustment_cap": MAX_OPTIONS_ADJUSTMENT,
            "same_scan_observation_is_not_independent_evidence": True,
            "automatic_adjustments_are_cohort_relative_not_absolute_win_probability": True,
        },
        "stock": stock,
        "options": options,
    }


def save_learning_model(path: str | Path, model: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def load_learning_model(path: str | Path) -> dict[str, Any]:
    payload = _load(path, {})
    return payload if isinstance(payload, dict) else {}


def stock_score_adjustment(model: dict[str, Any], row: dict[str, Any]) -> float:
    stock = model.get("stock") if isinstance(model.get("stock"), dict) else {}
    if not stock.get("ready"):
        return 0.0
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    keys = [
        ("score_bands", score_band(row.get("score"))),
        ("stages", str(row.get("stage") or "unknown")),
        ("regimes", str(row.get("market_regime") or "unknown")),
        ("cause_tiers", str(cause.get("source_tier") or "unknown")),
    ]
    adjustment = 0.0
    for group_name, key in keys:
        group = stock.get(group_name) if isinstance(stock.get(group_name), dict) else {}
        evidence = group.get(key) if isinstance(group.get(key), dict) else {}
        if evidence.get("eligible"):
            adjustment += _number(evidence.get("score_adjustment"))
    return round(max(-MAX_STOCK_ADJUSTMENT, min(MAX_STOCK_ADJUSTMENT, adjustment)), 2)


def options_score_adjustment(model: dict[str, Any], row: dict[str, Any]) -> float:
    options = model.get("options") if isinstance(model.get("options"), dict) else {}
    if not options.get("ready"):
        return 0.0
    keys = [
        ("score_bands", score_band(row.get("score"))),
        ("regimes", str(row.get("market_regime") or "unknown")),
        ("sides", str(row.get("option_type") or "").lower()),
    ]
    adjustment = 0.0
    for group_name, key in keys:
        group = options.get(group_name) if isinstance(options.get(group_name), dict) else {}
        evidence = group.get(key) if isinstance(group.get(key), dict) else {}
        if evidence.get("eligible"):
            adjustment += _number(evidence.get("score_adjustment"))
    return round(max(-MAX_OPTIONS_ADJUSTMENT, min(MAX_OPTIONS_ADJUSTMENT, adjustment)), 2)
