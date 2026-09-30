from __future__ import annotations

import argparse
import json
from pathlib import Path

from options_radar.black_box_fusion import FusionPolicy, fuse_paths, investigate_candidate, infer_market_regime, load_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BLACK BOX Omega evidence fusion.")
    parser.add_argument("--latest", default="public/data/latest.json")
    parser.add_argument("--explosion", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--flow", default="data/live/delta_signals.json")
    parser.add_argument("--options", default="public/data/options_latest.json")
    parser.add_argument("--output", default="data/live/black_box_omega.json")
    parser.add_argument("--max-candidates", type=int, default=25)
    args = parser.parse_args()

    result = fuse_paths(
        latest_path=args.latest,
        explosion_path=args.explosion,
        flow_path=args.flow,
        options_path=args.options,
        output_path=args.output,
        policy=FusionPolicy(max_candidates=max(1, args.max_candidates)),
    )
    investigations = [investigate_candidate(item) for item in result.get("candidates", [])]
    result["investigations"] = investigations
    result["investigation_summary"] = {
        "conflict_count": sum(item.get("conflict_state") == "CONFLICT" for item in investigations),
        "research_candidate_count": sum(item.get("research_state") == "RESEARCH_CANDIDATE" for item in investigations),
    }
    # Regime is optional: only explicitly supplied observations are used.
    latest_payload = load_json(args.latest)
    regime_payload = latest_payload.get("market_regime") if isinstance(latest_payload, dict) else {}
    if isinstance(regime_payload, dict):
        result["market_regime"] = infer_market_regime(regime_payload)
    else:
        result["market_regime"] = infer_market_regime({})
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
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
