from __future__ import annotations

import argparse
import json
from pathlib import Path

from options_radar.black_box_fusion import FusionPolicy, fuse_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BLACK BOX Omega evidence fusion.")
    parser.add_argument("--latest", default="public/data/latest.json")
    parser.add_argument("--explosion", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--flow", default="data/live/delta_signals.json")
    parser.add_argument("--output", default="data/live/black_box_omega.json")
    parser.add_argument("--max-candidates", type=int, default=25)
    args = parser.parse_args()

    result = fuse_paths(
        latest_path=args.latest,
        explosion_path=args.explosion,
        flow_path=args.flow,
        output_path=args.output,
        policy=FusionPolicy(max_candidates=max(1, args.max_candidates)),
    )
    summary = {
        "candidate_count": result["candidate_count"],
        "research_candidates": sum(
            item.get("research_state") == "RESEARCH_CANDIDATE"
            for item in result.get("candidates", [])
        ),
        "output": str(Path(args.output)),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
