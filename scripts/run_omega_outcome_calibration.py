from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from options_radar.calibration import build_calibration_report
from options_radar.outcomes import SignalJournal


def main() -> int:
    parser = argparse.ArgumentParser(description="Update path-aware outcomes and calibration.")
    parser.add_argument("--signals", default="data/live/signals.jsonl")
    parser.add_argument("--outcomes", default="data/live/outcomes.json")
    parser.add_argument("--calibration", default="data/live/calibration.json")
    parser.add_argument("--minimum-sample", type=int, default=100)
    args = parser.parse_args()

    journal = SignalJournal(
        Path(args.signals),
        Path(args.outcomes),
        model_version="black-box-omega",
    )
    summary = journal.update_outcomes(datetime.now(timezone.utc))
    report = build_calibration_report(
        args.signals,
        args.outcomes,
        minimum_sample=args.minimum_sample,
    )
    payload = {
        "schema": "omega-outcome-calibration-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcome_summary": summary,
        "calibration": report,
        "policy": {
            "automatic_execution": False,
            "automatic_weight_changes": False,
            "score_is_probability": False,
        },
    }
    destination = Path(args.calibration)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
