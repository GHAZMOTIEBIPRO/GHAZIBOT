from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.omega_engine import apply_omega
from options_radar.omega_observability import write_status_files
from options_radar.phase62_policy import apply_phase62_overlay
from options_radar.settings import Settings


def main() -> int:
    path = ROOT / "public/data/latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = apply_phase62_overlay(payload, Settings())
    apply_omega(payload)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    write_status_files(path, payload)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    summary = payload.get("summary", {})
    print(
        "Phase 6.2 + Ω evidence layers applied: "
        f"stocks A/B/C={summary.get('stock_tier_a', 0)}/"
        f"{summary.get('stock_tier_b', 0)}/{summary.get('stock_tier_c', 0)}, "
        f"contracts A/B/C={summary.get('contract_tier_a', 0)}/"
        f"{summary.get('contract_tier_b', 0)}/{summary.get('contract_tier_c', 0)}, "
        f"omega ranked={summary.get('omega_ranked', 0)}, "
        f"watchlist={summary.get('contract_watchlist', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
