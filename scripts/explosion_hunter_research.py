"""Build fail-closed Explosion Hunter research evidence from the existing fast-radar state."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.explosion_hunter_profile import classify_candidate  # noqa: E402


def build_report(payload: dict, *, now: datetime | None = None) -> dict:
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict):
        symbols = {}
    rows = []
    missing_by_field = {field: 0 for field in (
        "rvol", "float_shares", "dollar_volume", "provider_quote_timestamp", "official_catalyst_url"
    )}
    for symbol, source in sorted(symbols.items()):
        if not isinstance(source, dict):
            continue
        row = dict(source)
        row["symbol"] = symbol
        for field in missing_by_field:
            if row.get(field) is None or row.get(field) == "":
                missing_by_field[field] += 1
        # Only explicit provider evidence is permitted. Never infer quote time
        # from generated_at or the scan timestamp.
        rows.append(classify_candidate(row, now=now))
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "research_only": True,
        "telegram_enabled": False,
        "target_return_pct": 100,
        "candidate_count": len(rows),
        "watch_count": sum(row["stage"] == "WATCH" for row in rows),
        "missing_evidence_counts": missing_by_field,
        "source_schema_compatible": not any(missing_by_field.values()) if rows else False,
        "input_status": "NO_CANDIDATES" if not rows else (
            "MISSING_REQUIRED_EVIDENCE" if any(missing_by_field.values()) else "FIELDS_PRESENT_NOT_VERIFIED"
        ),
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/live/fast_market_state.json")
    parser.add_argument("--output", default="data/live/explosion_hunter_research.json")
    args = parser.parse_args()
    source = Path(args.input)
    if not source.exists():
        print("Hunter: no fast-market state; skipping without fabricating data")
        return 0
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"Hunter: invalid fast-market state: {type(exc).__name__}")
        return 1
    report = build_report(payload if isinstance(payload, dict) else {})
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Hunter research: candidates={report['candidate_count']} watch={report['watch_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
