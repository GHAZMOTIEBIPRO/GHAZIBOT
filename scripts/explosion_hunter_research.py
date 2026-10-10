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
from options_radar.microcap_hunter import assess_microcap_candidate  # noqa: E402


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
            value = row.get(field)
            if field in {"rvol", "float_shares", "dollar_volume"}:
                try:
                    missing = value is None or float(value) <= 0
                except (TypeError, ValueError):
                    missing = True
            else:
                missing = value is None or value == ""
            if missing:
                missing_by_field[field] += 1
        # Only explicit provider evidence is permitted. Never infer quote time
        # from generated_at or the scan timestamp.
        strict = classify_candidate(row, now=now)
        strict["microcap_hunter"] = assess_microcap_candidate(row).as_dict()
        rows.append(strict)
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "research_only": True,
        "telegram_enabled": False,
        "target_return_pct": 100,
        "candidate_count": len(rows),
        "watch_count": sum(row["stage"] == "WATCH" for row in rows),
        "microcap_priority_count": sum(
            (row.get("microcap_hunter") or {}).get("stage") == "PRIORITY"
            for row in rows
        ),
        "microcap_avoid_risk_count": sum(
            (row.get("microcap_hunter") or {}).get("stage") == "AVOID_RISK"
            for row in rows
        ),
        "microcap_policy": {
            "research_only": True,
            "live_score_adjustment": False,
            "third_party_scraping_added": False,
            "float_rvol_dilution_are_measured_separately": True,
        },
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
    print(
        "Hunter research: "
        f"candidates={report['candidate_count']} "
        f"watch={report['watch_count']} "
        f"microcap_priority={report['microcap_priority_count']} "
        f"avoid_risk={report['microcap_avoid_risk_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
