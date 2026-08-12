from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.occ_expiry_overlay import apply_expiry_radar_with_occ
from options_radar.omega_engine import apply_omega
from options_radar.omega_observability import write_status_files
from options_radar.option_contract_intelligence import apply_option_contract_intelligence
from options_radar.settings import Settings


def main() -> int:
    path = ROOT / "public/data/latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    # The contract-rationale engine must see a meaningful pool per symbol, not
    # only a tiny global top-N list. Keep the public tab bounded but large
    # enough to preserve near-horizon alternatives before selecting one contract.
    configured_top = int(os.getenv("EXPIRY_RADAR_TOP_PER_SIDE", "8") or 8)
    os.environ["EXPIRY_RADAR_TOP_PER_SIDE"] = str(max(40, configured_top))

    payload = apply_expiry_radar_with_occ(payload, Settings())
    apply_omega(payload)
    apply_option_contract_intelligence(payload)
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

    occ_path = ROOT / "data/live/occ_audit.json"
    occ_path.parent.mkdir(parents=True, exist_ok=True)
    occ_payload = payload.get("expiry_radar", {}).get("occ_official_context", {})
    occ_path.write_text(
        json.dumps(occ_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    summary = payload.get("expiry_radar", {}).get("summary", {})
    omega_summary = payload.get("omega", {}).get("summary", {})
    option_choices = payload.get("option_contract_intelligence", {}).get("symbols_with_contract_choice", 0)
    print(
        "Expiry radar + Ω + option rationale applied: "
        f"stocks={summary.get('symbols_scanned', 0)}, "
        f"daily={summary.get('daily', 0)}, "
        f"weekly={summary.get('weekly', 0)}, "
        f"monthly={summary.get('monthly', 0)}, "
        f"occ_symbols={summary.get('occ_successful_symbols', 0)}, "
        f"occ_reports={summary.get('occ_successful_reports', 0)}, "
        f"omega_ranked={omega_summary.get('ranked', 0)}, "
        f"option_choices={option_choices}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
