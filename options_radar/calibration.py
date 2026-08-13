from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCORE_BANDS = ((90, 101), (80, 90), (70, 80), (60, 70), (0, 60))
DEFAULT_MATURITY_CHECKPOINT = "1d"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _band(score: float) -> str:
    for low, high in SCORE_BANDS:
        if low <= score < high:
            return f"{low}-{high - 1}"
    return "unknown"


def _has_checkpoint(outcome: dict[str, Any], checkpoint: str) -> bool:
    checkpoints = outcome.get("checkpoints", {})
    return isinstance(checkpoints, dict) and isinstance(checkpoints.get(checkpoint), dict)


def _target_1_success(outcome: dict[str, Any]) -> bool:
    # outcomes.py makes stop-first terminal and same-bar collisions ambiguous.
    # A successful terminal path therefore means target 1 was reached before stop.
    return str(outcome.get("terminal_outcome") or "open") == "success"


def _target_2_success(outcome: dict[str, Any]) -> bool:
    if str(outcome.get("terminal_outcome") or "open") != "success":
        return False
    if str(outcome.get("outcome_order") or "") == "target_2_first":
        return True
    return bool(outcome.get("target_2_observed_snapshot"))


def _stop_failure(outcome: dict[str, Any]) -> bool:
    return str(outcome.get("terminal_outcome") or "open") == "failed"


def build_calibration_report(
    signals_path: str | Path = "data/live/signals.jsonl",
    outcomes_path: str | Path = "data/live/outcomes.json",
    minimum_sample: int = 100,
    maturity_checkpoint: str = DEFAULT_MATURITY_CHECKPOINT,
) -> dict[str, Any]:
    """Build a calibration report from temporally mature, path-aware evidence.

    Same-scan quotes are monitoring only. Mature evidence must have the requested
    checkpoint. Stop-first failures remain failures even if a later snapshot
    eventually trades above a target, and same-bar ambiguity is never a win.
    """

    signals = _load_jsonl(Path(signals_path))
    outcomes_payload = _load_json(Path(outcomes_path), {"signals": {}})
    outcomes = outcomes_payload.get("signals", {}) if isinstance(outcomes_payload, dict) else {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    raw_priced_total = 0
    matured_total = 0
    five_day_total = 0

    for signal in signals:
        signal_id = str(signal.get("signal_id", ""))
        outcome = outcomes.get(signal_id)
        if not signal_id or not isinstance(outcome, dict):
            continue
        if int(outcome.get("observations", 0) or 0) > 0:
            raw_priced_total += 1
        if _has_checkpoint(outcome, "5d"):
            five_day_total += 1
        score = float(signal.get("score", 0) or 0)
        grouped.setdefault(_band(score), []).append({"signal": signal, "outcome": outcome})

    bands: list[dict[str, Any]] = []
    for low, high in SCORE_BANDS:
        label = f"{low}-{high - 1}"
        rows = grouped.get(label, [])
        observed = [
            row for row in rows if int(row["outcome"].get("observations", 0) or 0) > 0
        ]
        matured = [
            row for row in rows if _has_checkpoint(row["outcome"], maturity_checkpoint)
        ]
        matured_total += len(matured)
        target1 = sum(_target_1_success(row["outcome"]) for row in matured)
        target2 = sum(_target_2_success(row["outcome"]) for row in matured)
        stopped = sum(_stop_failure(row["outcome"]) for row in matured)
        ambiguous = sum(str(row["outcome"].get("terminal_outcome") or "") == "ambiguous" for row in matured)
        mfe = [float(row["outcome"].get("mfe_pct", 0) or 0) for row in matured]
        mae = [float(row["outcome"].get("mae_pct", 0) or 0) for row in matured]
        bands.append(
            {
                "band": label,
                "signals": len(rows),
                "observed": len(observed),
                "priced": len(matured),
                "matured": len(matured),
                "target_1_rate": target1 / len(matured) if matured else None,
                "target_2_rate": target2 / len(matured) if matured else None,
                "stop_rate": stopped / len(matured) if matured else None,
                "ambiguous_rate": ambiguous / len(matured) if matured else None,
                "average_mfe_pct": sum(mfe) / len(mfe) if mfe else None,
                "average_mae_pct": sum(mae) / len(mae) if mae else None,
            }
        )

    catalyst_summary: dict[str, dict[str, float | int]] = {}
    for signal in signals:
        signal_id = str(signal.get("signal_id", ""))
        outcome = outcomes.get(signal_id)
        if not isinstance(outcome, dict) or not _has_checkpoint(outcome, maturity_checkpoint):
            continue
        catalyst = str(signal.get("catalyst", "none")).split(":", 1)[0][:80] or "none"
        row = catalyst_summary.setdefault(
            catalyst,
            {"signals": 0, "target_1": 0, "stops": 0, "ambiguous": 0, "mfe_sum": 0.0},
        )
        row["signals"] = int(row["signals"]) + 1
        row["target_1"] = int(row["target_1"]) + int(_target_1_success(outcome))
        row["stops"] = int(row["stops"]) + int(_stop_failure(outcome))
        row["ambiguous"] = int(row["ambiguous"]) + int(str(outcome.get("terminal_outcome") or "") == "ambiguous")
        row["mfe_sum"] = float(row["mfe_sum"]) + float(outcome.get("mfe_pct", 0) or 0)

    catalysts = []
    for name, row in sorted(
        catalyst_summary.items(), key=lambda item: int(item[1]["signals"]), reverse=True
    )[:12]:
        count = int(row["signals"])
        catalysts.append(
            {
                "catalyst": name,
                "signals": count,
                "target_1_rate": int(row["target_1"]) / count if count else None,
                "stop_rate": int(row["stops"]) / count if count else None,
                "ambiguous_rate": int(row["ambiguous"]) / count if count else None,
                "average_mfe_pct": float(row["mfe_sum"]) / count if count else None,
            }
        )

    ready = matured_total >= minimum_sample
    return {
        "sample_size": len(signals),
        "raw_priced_sample": raw_priced_total,
        "priced_sample": matured_total,
        "matured_sample": matured_total,
        "five_day_sample": five_day_total,
        "maturity_checkpoint": maturity_checkpoint,
        "minimum_sample": minimum_sample,
        "calibration_ready": ready,
        "decision": (
            "Eligible for independent score recalibration review"
            if ready
            else (
                f"Collect {max(0, minimum_sample - matured_total)} more signals with a "
                f"{maturity_checkpoint} checkpoint before changing weights"
            )
        ),
        "score_bands": bands,
        "catalysts": catalysts,
        "warning": (
            "Same-scan quotes are monitoring observations, not mature evidence. "
            f"The review gate counts only signals with a {maturity_checkpoint} checkpoint. "
            "Stop-first is terminal and same-bar ambiguity is never counted as a win. "
            "Free-data prices still do not prove executable fills."
        ),
    }
