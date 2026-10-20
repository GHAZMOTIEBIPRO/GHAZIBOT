"""CLI: publish per-symbol signal follow-up. Loads its module by path so it
runs in the dependency-free walk-forward job (no pandas)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "options_radar" / "signal_tracking.py"
    spec = importlib.util.spec_from_file_location("_ghazi_signal_tracking", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build


build = _load()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Signal tracking skipped: audit unreadable ({type(exc).__name__}).")
        return 0
    report = build(audit, now=datetime.now(timezone.utc))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Signal tracking: symbols={len(report['symbols'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
