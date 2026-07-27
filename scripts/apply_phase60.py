from __future__ import annotations

import json
import sys
from pathlib import Path

# Direct execution from scripts/ must still import the repository package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.phase61_overlay import apply_phase61_overlay
from options_radar.settings import Settings


def main() -> int:
    path = ROOT / "public/data/latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = apply_phase61_overlay(payload, Settings())
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    print(
        "Phase 6.1 intelligence overlay applied: "
        f"{len(payload.get('stock_recommendations', []))} stocks, "
        f"{len(payload.get('contract_recommendations', []))} contracts, "
        f"{payload.get('summary', {}).get('external_sources_successful', 0)} external sources active"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
