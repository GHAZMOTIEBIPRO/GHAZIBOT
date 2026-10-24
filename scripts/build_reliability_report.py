"""Single-writer first-observed fingerprints and a public metadata-only digest.

Fingerprints begin at this audit pass, not retroactively at Telegram delivery.
They detect changed entry evidence, not prove delivery, immutable storage or P/L.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from options_radar.audit_quality import validate_audit

ENTRY_FIELDS = ("signal_id", "signal_time", "symbol", "direction", "entry_price",
                "entry_stage", "entry_score", "follow_through_target_pct", "failure_threshold_pct")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def update_ledger(audit: dict, ledger: dict, *, now: datetime) -> tuple[dict, dict]:
    if ledger and (ledger.get("schema") != "ghazi.audit_fingerprints.v1"
                   or not isinstance(ledger.get("entries"), dict)):
        raise ValueError("invalid existing fingerprint ledger; refusing reset")
    entries = dict(ledger.get("entries", {}))
    added = conflicts = 0
    for row in audit.get("records", {}).values():
        if not isinstance(row, dict) or not row.get("signal_id"):
            continue
        identity = digest(row["signal_id"])
        fingerprint = digest({key: row.get(key) for key in ENTRY_FIELDS})
        previous = entries.get(identity)
        if previous is None:
            entries[identity] = {"entry_hash": fingerprint, "first_observed_at": now.isoformat(),
                                 "entry_changed": False}
            added += 1
        elif previous["entry_hash"] != fingerprint:
            entries[identity] = {**previous, "entry_changed": True}
            conflicts += 1
    summary = {"tracked": len(entries), "added": added, "conflicts_this_pass": conflicts,
               "ever_changed": sum(v["entry_changed"] is True for v in entries.values()),
               "delivery_proven": False, "scope": "first_observed_by_auditor"}
    return {"schema": "ghazi.audit_fingerprints.v1", "entries": entries}, summary


def build_report(audit: dict, ledger: dict, stats: dict, *, now: datetime) -> tuple[dict, dict]:
    quality = validate_audit(audit, now=now)
    if quality["status"] == "VALID":
        updated, integrity = update_ledger(audit, ledger, now=now)
    else:
        updated = ledger
        integrity = {"tracked": len(ledger.get("entries", {})), "added": 0,
                     "conflicts_this_pass": 0, "ever_changed": None,
                     "delivery_proven": False, "scope": "not_checked_invalid_or_empty_input"}
    matching_stats = (quality["status"] == "VALID" and stats.get("audit_sha256") == digest(audit)
                      and stats.get("completed_bar_measurement_required") is True
                      and stats.get("decision_authority") is False
                      and stats.get("status") in {"RESEARCH_METRICS_ONLY", "INSUFFICIENT_EVIDENCE", "UNAVAILABLE"})
    report = {"schema": "ghazi.reliability.v1", "generated_at": now.isoformat(),
              "decision_authority": False, "execution_grade": False, "proven_edge": False,
              "quality": quality, "integrity": integrity,
              "statistics_input_verified": matching_stats,
              "statistics_status": stats.get("status", "UNAVAILABLE") if matching_stats
              and integrity["ever_changed"] == 0 else "WITHHELD",
              "cost_scenarios_are_hypothetical": True, "raw_market_data_published": False,
              "reason_ar": "فحص بنية البيانات وبصمة أول مشاهدة في المدقق؛ لا يثبت إرسال التنبيه أو ربحية التداول."}
    return report, updated


def read(path: Path, *, optional: bool = False) -> dict:
    if optional and not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError("expected JSON object")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("audit", "ledger", "stats", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report, ledger = build_report(read(args.audit), read(args.ledger, optional=True), read(args.stats),
                                  now=datetime.now(timezone.utc))
    if ledger:
        write(args.ledger, ledger)
    write(args.output, report)
    print("Reliability:", report["quality"], report["integrity"])


if __name__ == "__main__":
    main()
