from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_ARCHIVE_RECORDS = 10_000


def _load(path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return dict(default)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _matured_decisive(state: dict[str, Any]) -> bool:
    checkpoints = state.get("checkpoints") if isinstance(state.get("checkpoints"), dict) else {}
    return "60m" in checkpoints and state.get("terminal_outcome") in {"success", "failed"}


def _archive_record(state: dict[str, Any]) -> dict[str, Any]:
    checkpoints = state.get("checkpoints") if isinstance(state.get("checkpoints"), dict) else {}
    selected_checkpoints = {
        label: value
        for label, value in checkpoints.items()
        if label in {"15m", "60m", "1d"} and isinstance(value, dict)
    }
    return {
        "signal_id": str(state.get("signal_id") or ""),
        "signal_time": state.get("signal_time"),
        "symbol": str(state.get("symbol") or "").upper(),
        "direction": str(state.get("direction") or "up"),
        "entry_price": state.get("entry_price"),
        "entry_stage": state.get("entry_stage", state.get("stage")),
        "entry_score": state.get("entry_score", state.get("score")),
        "entry_score_band": state.get("entry_score_band", state.get("score_band")),
        "stage": state.get("stage"),
        "score": state.get("score"),
        "score_band": state.get("score_band"),
        "market_regime": state.get("market_regime"),
        "cause_category": state.get("cause_category"),
        "cause_tier": state.get("cause_tier"),
        "official_cause": bool(state.get("official_cause")),
        "entry_evidence_state": state.get("entry_evidence_state", "LEGACY_UNKNOWN"),
        "entry_cause_status": state.get("entry_cause_status", "LEGACY_UNKNOWN"),
        "follow_through_target_pct": state.get("follow_through_target_pct"),
        "failure_threshold_pct": state.get("failure_threshold_pct"),
        "terminal_outcome": state.get("terminal_outcome"),
        "terminal_reason": state.get("terminal_reason"),
        "terminal_at": state.get("terminal_at"),
        "mfe_pct": state.get("mfe_pct"),
        "mae_pct": state.get("mae_pct"),
        "checkpoints": selected_checkpoints,
        "measurement_basis": state.get("measurement_basis", "repeated_radar_snapshots"),
        "event_level_deduped": True,
    }


@dataclass(frozen=True)
class StockArchiveSummary:
    records: int
    successes: int
    failures: int
    added_this_pass: int
    updated_this_pass: int

    def as_dict(self) -> dict[str, int]:
        return {
            "records": self.records,
            "successes": self.successes,
            "failures": self.failures,
            "added_this_pass": self.added_this_pass,
            "updated_this_pass": self.updated_this_pass,
        }


def update_stock_outcome_archive(
    stock_outcomes_path: str | Path,
    archive_path: str | Path,
    *,
    now: datetime | None = None,
    maximum_records: int = MAX_ARCHIVE_RECORDS,
) -> dict[str, Any]:
    """Append matured decisive event samples without changing live stock state.

    The live tracker intentionally retains a short operational window. This
    archive keeps deduplicated event-level evidence long enough for statistical
    review. It is research state only and has no direct alert authority.
    """

    stock_state = _load(stock_outcomes_path, {"signals": {}})
    archive = _load(
        archive_path,
        {
            "schema_version": 1,
            "updated_at": None,
            "records": {},
        },
    )
    records = archive.get("records") if isinstance(archive.get("records"), dict) else {}
    records = {str(key): value for key, value in records.items() if isinstance(value, dict)}
    signals = stock_state.get("signals") if isinstance(stock_state.get("signals"), dict) else {}

    added = 0
    updated = 0
    for state in signals.values():
        if not isinstance(state, dict) or not _matured_decisive(state):
            continue
        signal_id = str(state.get("signal_id") or "").strip()
        if not signal_id:
            continue
        record = _archive_record(state)
        previous = records.get(signal_id)
        if previous is None:
            records[signal_id] = record
            added += 1
        elif previous != record:
            # Same event identity may gain a later 1d checkpoint or richer MFE/MAE.
            # Updating it is not a new sample and therefore never inflates n.
            records[signal_id] = record
            updated += 1

    limit = max(100, int(maximum_records))
    if len(records) > limit:
        ordered = sorted(
            records.items(),
            key=lambda item: (_parse_time(item[1].get("signal_time")), item[0]),
            reverse=True,
        )[:limit]
        records = dict(ordered)

    successes = sum(row.get("terminal_outcome") == "success" for row in records.values())
    failures = sum(row.get("terminal_outcome") == "failed" for row in records.values())
    summary = StockArchiveSummary(
        records=len(records),
        successes=successes,
        failures=failures,
        added_this_pass=added,
        updated_this_pass=updated,
    )
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    archive = {
        "schema_version": 1,
        "updated_at": current.astimezone(timezone.utc).isoformat(),
        "mode": "EVENT_LEVEL_DECISIVE_ARCHIVE",
        "decision_authority": False,
        "maximum_records": limit,
        "measurement_note": (
            "Historical research archive of deduplicated stock events. Entries require a 60m checkpoint "
            "and a decisive success/failed terminal outcome. Entry catalyst evidence is frozen when available; "
            "legacy rows remain explicitly LEGACY_UNKNOWN rather than being backfilled with future information."
        ),
        "records": records,
        "summary": summary.as_dict(),
    }
    _write(archive_path, archive)
    return archive
