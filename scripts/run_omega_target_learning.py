from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.omega_target_learning import OmegaTargetLearning


def _load(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read Omega payload: {source}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Omega payload must be a JSON object")
    return payload


def _time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record and update Omega underlying T1/T2/T3 target-learning evidence."
    )
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--state", default="data/live/omega_target_state.json")
    parser.add_argument("--calibration", default="data/live/omega_target_calibration.json")
    args = parser.parse_args()

    payload = _load(args.payload)
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    opportunities = [
        row for row in omega.get("opportunities", [])
        if isinstance(row, dict)
    ]
    generated_at = _time(payload.get("generated_at"))
    learner = OmegaTargetLearning(
        state_path=Path(args.state),
        calibration_path=Path(args.calibration),
    )
    result = learner.run(
        opportunities,
        generated_at=generated_at,
        now=datetime.now(timezone.utc),
    )
    calibration = result["calibration"]
    summary = result["state_summary"]
    print(
        "Omega target learning: "
        f"added={result['added']} "
        f"signals={summary.get('signals', 0)} "
        f"matured_targets={summary.get('matured_targets', 0)} "
        f"hits={summary.get('hits', 0)} "
        f"calibration_ready={calibration.get('calibration_ready')} "
        f"matured_t1={calibration.get('global_matured_t1_sample', 0)}/"
        f"{calibration.get('minimum_global_sample', 100)}"
    )


if __name__ == "__main__":
    main()
