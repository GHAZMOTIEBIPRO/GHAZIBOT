from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stock_outcomes import StockOutcomeTracker, _parse_time, _write

REENTRY_GAP_MINUTES = 4 * 60


def _state_time(state: dict[str, Any]) -> datetime:
    return _parse_time(state.get("signal_time")) or datetime.min.replace(tzinfo=timezone.utc)


def _history_entry(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "observed_at": state.get("signal_time"),
        "stage": state.get("stage"),
        "score": state.get("score"),
        "score_band": state.get("score_band"),
    }


def _merge_primary(primary: dict[str, Any], duplicate: dict[str, Any]) -> None:
    primary.setdefault("entry_stage", primary.get("stage"))
    primary.setdefault("entry_score", primary.get("score"))
    primary.setdefault("entry_score_band", primary.get("score_band"))
    history = primary.setdefault("stage_history", [])
    if not history:
        history.append(_history_entry(primary))
    duplicate_entry = _history_entry(duplicate)
    signature = (
        duplicate_entry.get("stage"),
        duplicate_entry.get("score_band"),
    )
    if signature not in {
        (item.get("stage"), item.get("score_band"))
        for item in history
        if isinstance(item, dict)
    }:
        history.append(duplicate_entry)

    primary["latest_stage"] = duplicate.get("latest_stage", duplicate.get("stage"))
    primary["latest_score"] = duplicate.get("latest_score", duplicate.get("score"))
    primary["latest_score_band"] = duplicate.get("latest_score_band", duplicate.get("score_band"))
    primary["observations"] = max(
        int(primary.get("observations", 0) or 0),
        int(duplicate.get("observations", 0) or 0),
    )
    primary["mfe_pct"] = max(
        float(primary.get("mfe_pct", 0.0) or 0.0),
        float(duplicate.get("mfe_pct", 0.0) or 0.0),
    )
    primary["mae_pct"] = min(
        float(primary.get("mae_pct", 0.0) or 0.0),
        float(duplicate.get("mae_pct", 0.0) or 0.0),
    )

    primary_time = _parse_time(primary.get("last_observed_at"))
    duplicate_time = _parse_time(duplicate.get("last_observed_at"))
    if duplicate_time and (primary_time is None or duplicate_time > primary_time):
        for key in (
            "last_observed_at",
            "last_price",
            "last_directional_return_pct",
        ):
            if key in duplicate:
                primary[key] = duplicate[key]

    primary_checkpoints = primary.setdefault("checkpoints", {})
    duplicate_checkpoints = duplicate.get("checkpoints") if isinstance(duplicate.get("checkpoints"), dict) else {}
    for label, value in duplicate_checkpoints.items():
        primary_checkpoints.setdefault(label, value)

    # The earliest event remains authoritative for terminal path semantics.
    # A later duplicate must never turn an earlier open/failed sample into a win.
    if str(primary.get("terminal_outcome") or "open") == "open":
        duplicate_outcome = str(duplicate.get("terminal_outcome") or "open")
        if duplicate_outcome == "failed":
            for key in ("terminal_outcome", "terminal_reason", "terminal_at"):
                if key in duplicate:
                    primary[key] = duplicate[key]


def dedupe_stock_outcome_payload(
    payload: dict[str, Any],
    *,
    reentry_gap_minutes: int = REENTRY_GAP_MINUTES,
) -> dict[str, Any]:
    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    rows = [state for state in signals.values() if isinstance(state, dict)]
    rows.sort(key=_state_time)
    kept: dict[str, dict[str, Any]] = {}
    active: dict[tuple[str, str], tuple[str, datetime]] = {}
    collapsed = 0

    for state in rows:
        signal_id = str(state.get("signal_id") or "")
        symbol = str(state.get("symbol") or "").upper()
        direction = str(state.get("direction") or "up").lower()
        created = _state_time(state)
        key = (symbol, direction)
        previous = active.get(key)
        if previous:
            primary_id, primary_time = previous
            gap = (created - primary_time).total_seconds() / 60.0
            if 0 <= gap < max(1, int(reentry_gap_minutes)):
                _merge_primary(kept[primary_id], state)
                collapsed += 1
                continue
        kept[signal_id] = dict(state)
        kept[signal_id].setdefault("entry_stage", kept[signal_id].get("stage"))
        kept[signal_id].setdefault("entry_score", kept[signal_id].get("score"))
        kept[signal_id].setdefault("entry_score_band", kept[signal_id].get("score_band"))
        kept[signal_id].setdefault("stage_history", [_history_entry(kept[signal_id])])
        active[key] = (signal_id, created)

    payload["signals"] = kept
    payload["event_dedup"] = {
        "mode": "same_symbol_direction_within_4h",
        "reentry_gap_minutes": max(1, int(reentry_gap_minutes)),
        "duplicates_collapsed_this_pass": collapsed,
        "samples_after_dedup": len(kept),
    }
    return payload


class EventLevelStockOutcomeTracker(StockOutcomeTracker):
    def update(self, stocks: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        payload = super().update(stocks, **kwargs)
        payload = dedupe_stock_outcome_payload(payload)
        payload["summary"] = self.summary(payload).as_dict()
        _write(Path(self.path), payload)
        return payload
