"""CLI: measured Explosion Hunter stage quality from the stock outcome audit."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from options_radar.explosion_stage_evaluation import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Stage evaluation skipped: audit unreadable ({type(exc).__name__}).")
        return 0
    report = evaluate(audit, now=datetime.now(timezone.utc))
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    print("Stage evaluation:", json.dumps(report["population"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
