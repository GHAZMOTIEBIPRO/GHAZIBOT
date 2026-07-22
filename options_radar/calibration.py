from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCORE_BANDS = ((90, 101), (80, 90), (70, 80), (60, 70), (0, 60))


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


def build_calibration_report(
    signals_path: str | Path = "data/live/signals.jsonl",
    outcomes_path: str | Path = "data/live/outcomes.json",
    minimum_sample: int = 100,
) -> dict[str, Any]:
    signals = _load_jsonl(Path(signals_path))
    outcomes_payload = _load_json(Path(outcomes_path), {"signals": {}})
    outcomes = outcomes_payload.get("signals", {}) if isinstance(outcomes_payload, dict) else {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        signal_id = str(signal.get("signal_id", ""))
        outcome = outcomes.get(signal_id)
        if not signal_id or not isinstance(outcome, dict):
            continue
        score = float(signal.get("score", 0) or 0)
        grouped.setdefault(_band(score), []).append({"signal": signal, "outcome": outcome})

    bands: list[dict[str, Any]] = []
    priced_total = 0
    for low, high in SCORE_BANDS:
        label = f"{low}-{high - 1}"
        rows = grouped.get(label, [])
        priced = [row for row in rows if int(row["outcome"].get("observations", 0) or 0) > 0]
        priced_total += len(priced)
        target1 = sum(bool(row["outcome"].get("target_1_observed")) for row in priced)
        target2 = sum(bool(row["outcome"].get("target_2_observed")) for row in priced)
        stopped = sum(bool(row["outcome"].get("stop_observed")) for row in priced)
        mfe = [float(row["outcome"].get("mfe_pct", 0) or 0) for row in priced]
        mae = [float(row["outcome"].get("mae_pct", 0) or 0) for row in priced]
        bands.append(
            {
                "band": label,
                "signals": len(rows),
                "priced": len(priced),
                "target_1_rate": target1 / len(priced) if priced else None,
                "target_2_rate": target2 / len(priced) if priced else None,
                "stop_rate": stopped / len(priced) if priced else None,
                "average_mfe_pct": sum(mfe) / len(mfe) if mfe else None,
                "average_mae_pct": sum(mae) / len(mae) if mae else None,
            }
        )

    catalyst_summary: dict[str, dict[str, float | int]] = {}
    for signal in signals:
        signal_id = str(signal.get("signal_id", ""))
        outcome = outcomes.get(signal_id)
        if not isinstance(outcome, dict) or int(outcome.get("observations", 0) or 0) <= 0:
            continue
        catalyst = str(signal.get("catalyst", "none")).split(":", 1)[0][:80] or "none"
        row = catalyst_summary.setdefault(
            catalyst,
            {"signals": 0, "target_1": 0, "stops": 0, "mfe_sum": 0.0},
        )
        row["signals"] = int(row["signals"]) + 1
        row["target_1"] = int(row["target_1"]) + int(bool(outcome.get("target_1_observed")))
        row["stops"] = int(row["stops"]) + int(bool(outcome.get("stop_observed")))
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
                "average_mfe_pct": float(row["mfe_sum"]) / count if count else None,
            }
        )

    ready = priced_total >= minimum_sample
    return {
        "sample_size": len(signals),
        "priced_sample": priced_total,
        "minimum_sample": minimum_sample,
        "calibration_ready": ready,
        "decision": (
            "Eligible for score recalibration review"
            if ready
            else f"Collect {max(0, minimum_sample - priced_total)} more priced signals before changing weights"
        ),
        "score_bands": bands,
        "catalysts": catalysts,
        "warning": (
            "Observed free-data prices do not prove trade execution or target/stop order. "
            "Do not optimize weights on a small sample."
        ),
    }
