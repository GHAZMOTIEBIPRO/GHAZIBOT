"""Write macro_regimes.json from the public-macro history (see options_radar/macro_regimes.py)."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ghazi_macro_regimes", ROOT / "options_radar" / "macro_regimes.py")
regimes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regimes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        history = json.loads(args.history.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("Macro regimes: no history;", type(exc).__name__)
        return 1
    report = regimes.build(history, generated_at=datetime.now(timezone.utc).isoformat())
    if report["status"] != "AVAILABLE":
        print("Macro regimes: no series validated; keeping the previous file.")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(args.output)
    print("Macro regimes:", json.dumps({k: (v.get("current_regime") or {}).get("since") or v.get("reason")
                                        for k, v in report["series"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
