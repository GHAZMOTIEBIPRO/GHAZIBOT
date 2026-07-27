from __future__ import annotations

import json
from pathlib import Path

import options_radar.phase60_overlay as overlay
from options_radar.phase60_source_network import build_source_network
from options_radar.settings import Settings

# Keep stock-source and option-source audit evidence independent.
overlay.build_source_network = build_source_network


def main() -> int:
    path = Path("public/data/latest.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = overlay.apply_phase60_overlay(payload, Settings())
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    print(
        "Phase 6 overlay applied: "
        f"{len(payload.get('stock_recommendations', []))} stocks, "
        f"{len(payload.get('contract_recommendations', []))} contracts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
