from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.occ_expiry_overlay import apply_expiry_radar_with_occ
from options_radar.settings import Settings


def main() -> int:
    path = ROOT / "public/data/latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = apply_expiry_radar_with_occ(payload, Settings())
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)

    occ_path = ROOT / "data/live/occ_audit.json"
    occ_path.parent.mkdir(parents=True, exist_ok=True)
    occ_payload = payload.get("expiry_radar", {}).get("occ_official_context", {})
    occ_path.write_text(
        json.dumps(occ_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    summary = payload.get("expiry_radar", {}).get("summary", {})
    print(
        "Expiry radar applied: "
        f"stocks={summary.get('symbols_scanned', 0)}, "
        f"daily={summary.get('daily', 0)}, "
        f"weekly={summary.get('weekly', 0)}, "
        f"monthly={summary.get('monthly', 0)}, "
        f"occ_symbols={summary.get('occ_successful_symbols', 0)}, "
        f"occ_reports={summary.get('occ_successful_reports', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
