"""Signal ledger cycle: adopt delivered alerts, monitor them, export the public page data.

This job adds no Telegram sender of its own for new alerts. New CONFIRMED
alerts are still sent only by ``scripts/send_strict_options_alerts.py``; this
cycle *adopts* each message that sender delivered (its message id and send
time come from the sender's state file), creates the ledger record with the
same deterministic ``signal_id`` the sender linked to, and then:

1. feeds every quote row found in the options payload to the monitor
   (no new data source and no fetching here);
2. edits the original Telegram message with the state history, and posts a
   short reply only for target / stop / invalidation / stale changes;
3. writes the private ledger (single writer) and the public JSON the page
   ``/options/signal/{id}`` reads, after the licence guard.

Telegram is off unless ``SIGNAL_LEDGER_TELEGRAM=1``; the ledger and the
page data are still produced. Exit code is 0 unless the ledger file itself
cannot be written.

Usage:
  python scripts/run_signal_ledger.py --payload public/data/options_latest.json \
      --sender-state data/live/options_telegram_alert_state.json \
      --ledger data/live/signal_ledger.json --public public/data/signal_ledger.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar import public_guard
from options_radar import signal_ledger as sl
from options_radar.execution_confidence import _parse_timestamp

QUOTE_LISTS = ("contracts", "research_directional_signals", "production_directional_signals",
               "directional_signals", "top_calls", "top_puts", "free_directional_signals")


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        tmp = fh.name
    os.replace(tmp, target)


def payload_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Latest row per OCC across the payload lists (the freshest quote wins)."""
    best: dict[str, dict[str, Any]] = {}
    for key in QUOTE_LISTS:
        for row in payload.get(key) or []:
            if not isinstance(row, dict):
                continue
            identity = sl.parse_occ(row.get("contract_symbol"))
            if identity is None:
                continue
            stamp = _parse_timestamp(row.get("quote_timestamp") or row.get("quote_time"))
            current = best.get(identity["occ"])
            current_stamp = _parse_timestamp((current or {}).get("quote_timestamp") or (current or {}).get("quote_time"))
            if current is None or (stamp and (current_stamp is None or stamp > current_stamp)):
                best[identity["occ"]] = row
    return best


def adopt_sent_alerts(ledger: dict[str, Any], sender_state: dict[str, Any], rows: dict[str, dict[str, Any]],
                      *, policy: sl.LedgerPolicy) -> list[str]:
    """Create ledger records for alerts the strict sender delivered."""
    notes: list[str] = []
    rejected = ledger.setdefault("unmonitored_alerts", {})
    for record in (sender_state.get("sent") or {}).values():
        if not isinstance(record, dict) or record.get("kind") != "options":
            continue
        occ = str(record.get("contract_symbol") or "").upper()
        sent_at = _parse_timestamp(record.get("sent_at"))
        if sl.parse_occ(occ) is None or sent_at is None:
            continue
        sid = sl.signal_id_for(occ, sl.ny_session(sent_at), policy.version)
        if sid in ledger["signals"] or sid in rejected:
            continue
        row = rows.get(occ)
        if row is None:
            rejected[sid] = {"occ": occ, "sent_at": record.get("sent_at"), "reason": "row_not_in_payload"}
            notes.append(f"{occ}: delivered alert not found in payload; not monitored")
            continue
        built = sl.build_signal(row, now=sent_at, policy=policy)
        if not built["accepted"]:
            rejected[sid] = {"occ": occ, "sent_at": record.get("sent_at"), "reason": built["rejections"]}
            notes.append(f"{occ}: ledger policy rejected {built['rejections']}")
            continue
        signal = built["signal"]
        sl.mark_published(signal, at=sent_at, message_id=record.get("message_id"))
        sl.upsert(ledger, signal)
        notes.append(f"{occ}: adopted as {sid}")
    return notes


def monitor(ledger: dict[str, Any], rows: dict[str, dict[str, Any]], *, now: datetime,
            policy: sl.LedgerPolicy) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    changes: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for signal in ledger["signals"].values():
        row = rows.get(signal["contract"]["occ"])
        events = sl.observe(signal, row, now=now, policy=policy) if row else []
        events += sl.sweep(signal, now=now, policy=policy)
        changes += [(signal, event) for event in events if event.get("type") == "STATE"]
    return changes


def deliver(changes: list[tuple[dict[str, Any], dict[str, Any]]], *, enabled: bool) -> dict[str, int]:
    counts = {"edited": 0, "replied": 0, "skipped": 0, "failed": 0}
    if not changes:
        return counts
    if not enabled:
        counts["skipped"] = len(changes)
        return counts
    from scripts.telegram_transport import edit_html_message, send_html_message

    edited: set[str] = set()
    for signal, event in changes:
        tg = signal.setdefault("telegram", {})
        attempts = tg.setdefault("attempts", [])
        message_id = tg.get("message_id")
        if not message_id or event.get("to") not in sl.NOTIFY_STATES:
            counts["skipped"] += 1
            continue
        try:
            if signal["signal_id"] not in edited:
                result = edit_html_message(int(message_id), sl.telegram_text(signal))
                edited.add(signal["signal_id"])
                counts["edited"] += 1
                attempts.append({"at": event["at"], "op": "edit", "ok": True, "unchanged": result.unchanged})
            if event.get("to") != sl.PAPER_ACTIVE:
                reply = send_html_message(sl.update_text(signal, event), disable_notification=False)
                counts["replied"] += 1
                attempts.append({"at": event["at"], "op": "reply", "ok": True, "message_id": reply.message_id,
                                 "state": event.get("to")})
        except Exception as exc:  # noqa: BLE001 - record and continue; never print secrets
            counts["failed"] += 1
            attempts.append({"at": event["at"], "op": "edit_or_reply", "ok": False, "error": type(exc).__name__})
        del attempts[:-20]
    return counts


def run(args: argparse.Namespace, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    policy = sl.DEFAULT_POLICY
    payload = _load(args.payload, {})
    sender_state = _load(args.sender_state, {"sent": {}}) if args.sender_state else {"sent": {}}
    ledger = _load(args.ledger, None) or sl.empty_ledger()
    if ledger.get("schema") != sl.SCHEMA:
        raise RuntimeError("ledger schema mismatch; refusing to overwrite")
    rows = payload_rows(payload if isinstance(payload, dict) else {})
    notes = adopt_sent_alerts(ledger, sender_state if isinstance(sender_state, dict) else {}, rows, policy=policy)
    changes = monitor(ledger, rows, now=now, policy=policy)
    counts = deliver(changes, enabled=os.getenv("SIGNAL_LEDGER_TELEGRAM", "").strip() == "1")
    ledger["updated_at"] = now.isoformat()
    _save_atomic(args.ledger, ledger)
    # Owner's record of providers whose written terms allow public display (comma-separated
    # source tokens). Empty by default, so contract prices on the public page stay withheld.
    display_sources = tuple(t.strip() for t in os.getenv("SIGNAL_PUBLIC_DISPLAY_SOURCES", "").split(",") if t.strip())
    public = sl.build_public_ledger(ledger, now=now, closed_families=public_guard.closed_families(),
                                    family_of=public_guard.family_of, display_sources=display_sources)
    if args.public:
        _save_atomic(args.public, public)
    report = {"signals": len(ledger["signals"]), "quote_rows": len(rows), "state_changes": len(changes),
              "telegram": counts, "notes": notes[-20:]}
    print(json.dumps(report, ensure_ascii=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="GHAZI signal ledger cycle")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--sender-state", default="")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--public", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
