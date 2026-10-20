"""CLI: measured Explosion Hunter stage quality from the stock outcome audit.

The walk-forward workflow installs no third-party packages, and importing
through the options_radar package pulls pandas in via its __init__. The
evaluator is standard-library only, so it is loaded directly by file path.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _load_evaluate() -> Callable[..., dict[str, Any]]:
    module_path = Path(__file__).resolve().parents[1] / "options_radar" / "explosion_stage_evaluation.py"
    spec = importlib.util.spec_from_file_location("_ghazi_explosion_stage_evaluation", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load stage evaluation module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.evaluate


evaluate = _load_evaluate()


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
