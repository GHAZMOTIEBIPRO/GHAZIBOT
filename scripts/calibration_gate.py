from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_output(name: str, value: str) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def evaluate(calibration_path: Path, marker_path: Path) -> int:
    report = _load(calibration_path, {})
    marker = _load(marker_path, {})
    ready = bool(report.get("calibration_ready"))
    already_opened = bool(marker.get("issue_url"))
    should_open = ready and not already_opened

    _write_output("ready", "true" if ready else "false")
    _write_output("should_open", "true" if should_open else "false")
    _write_output("priced_sample", str(int(report.get("priced_sample", 0) or 0)))
    _write_output("minimum_sample", str(int(report.get("minimum_sample", 100) or 100)))
    _write_output("existing_issue_url", str(marker.get("issue_url", "")))
    return 0


def mark(marker_path: Path, issue_url: str) -> int:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "issue_url": issue_url,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "calibration_review_gate",
        "automatic_weight_changes": False,
    }
    temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(marker_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", default="data/live/calibration.json")
    parser.add_argument("--marker", default="data/live/calibration_issue.json")
    parser.add_argument("--mark", metavar="ISSUE_URL")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    calibration = Path(args.calibration)
    marker = Path(args.marker)
    if args.mark:
        return mark(marker, args.mark)
    return evaluate(calibration, marker)


if __name__ == "__main__":
    raise SystemExit(main())
