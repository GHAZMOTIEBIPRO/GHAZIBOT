from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.expiry_radar import apply_expiry_radar
from options_radar.settings import Settings


def main() -> int:
    path = ROOT / "public/data/latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = apply_expiry_radar(payload, Settings())
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    summary = payload.get("expiry_radar", {}).get("summary", {})
    print(
        "Expiry radar applied: "
        f"stocks={summary.get('symbols_scanned', 0)}, "
        f"daily={summary.get('daily', 0)}, "
        f"weekly={summary.get('weekly', 0)}, "
        f"monthly={summary.get('monthly', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
