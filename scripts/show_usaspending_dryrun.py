"""Print a short evidence summary of a USAspending dry run (branch probe workflow only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    gov = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cat = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print("COMPANIES", json.dumps(gov["companies"]))
    for a in gov["actions"][:12]:
        print("ACTION", json.dumps({k: a.get(k) for k in ("symbol", "action_date", "award_id", "modification", "agency",
                                                          "action_obligation", "award_total_obligation", "award_ceiling",
                                                          "award_total_outlay", "recipient", "parent_recipient")}))
    events = [e for e in cat.get("events", []) if e.get("source") == "USAspending"]
    print("CATALYST_EVENTS", len(events), json.dumps(cat.get("sources", {}).get("usaspending")))
    for e in events[:8]:
        print("EVENT", json.dumps({k: e.get(k) for k in ("symbol", "kind", "date", "importance", "label",
                                                         "first_seen_basis")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
