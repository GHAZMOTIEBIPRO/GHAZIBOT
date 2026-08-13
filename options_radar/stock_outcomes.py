from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECKPOINTS_MINUTES = {"15m": 15, "60m": 60, "1d": 24 * 60}
STAGE_THRESHOLDS = {
    "PRESSURE_BUILDING": (8.0, 5.0),
    "IGNITION": (10.0, 6.0),
    "EXPLOSION": (6.0, 6.0),
}
TRACKABLE_STAGES = frozenset(STAGE_THRESHOLDS)
EVENT_REENTRY_SECONDS = 4 * 60 * 60


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 2, "updated_at": None, "signals": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 2, "updated_at": None, "signals": {}}
    if not isinstance(payload, dict):
        return {"schema_version": 2, "updated_at": None, "signals": {}}
    payload.setdefault("schema_version", 1)
    payload.setdefault("signals", {})
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _band(score: float) -> str:
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 72:
        return "72-79"
    return "below-72"


def _history_item(state: dict[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    return {
        "observed_at": observed_at or str(state.get("signal_time") or ""),
        "stage": str(state.get("stage") or "").upper(),
        "score": round(_number(state.get("score"), 0.0) or 0.0, 4),
        "score_band": str(state.get("score_band") or _band(_number(state.get("score"), 0.0) or 0.0)),
    }


@dataclass(frozen=True)
class StockOutcomeSummary:
    tracked: int
    matured_60m: int
    successes: int
    failures: int
    open: int

    def as_dict(self) -> dict[str, int]:
        return {
            "tracked": self.tracked,
            "matured_60m": self.matured_60m,
            "successes": self.successes,
            "failures": self.failures,
            "open": self.open,
        }


class StockOutcomeTracker:
    """Learn from repeated stock-radar snapshots without blocking the live scan.

    One market event is one learning sample. Stage promotion or a score-band
    change inside the same four-hour event window is recorded in ``stage_history``
    and never creates a second sample. The original entry stage, score, price and
    thresholds remain immutable so later information cannot leak into the entry.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @staticmethod
    def _signal_id(row: dict[str, Any], now: datetime) -> str:
        symbol = str(row.get("symbol") or "").upper().strip()
        key = f"{symbol}|{now.isoformat()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _direction(row: dict[str, Any]) -> str:
        return "down" if (_number(row.get("move_pct"), 0.0) or 0.0) < 0 else "up"

    @staticmethod
    def _cause_fields(row: dict[str, Any]) -> tuple[str, str, bool]:
        cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
        return (
            str(cause.get("category") or "unknown")[:80],
            str(cause.get("source_tier") or "unknown")[:40],
            bool(cause.get("official_confirmed")),
        )

    @staticmethod
    def _append_stage_history(state: dict[str, Any], row: dict[str, Any], now: datetime) -> None:
        stage = str(row.get("stage") or "").upper()
        score = _number(row.get("score"), 0.0) or 0.0
        item = {
            "observed_at": now.isoformat(),
            "stage": stage,
            "score": round(score, 4),
            "score_band": _band(score),
        }
        history = state.setdefault("stage_history", [])
        if not isinstance(history, list):
            history = []
            state["stage_history"] = history
        if not history:
            history.append(_history_item(state))
        last = history[-1] if isinstance(history[-1], dict) else {}
        if last.get("stage") != item["stage"] or last.get("score_band") != item["score_band"]:
            history.append(item)

    @staticmethod
    def _observe(state: dict[str, Any], price: float, now: datetime) -> None:
        entry = _number(state.get("entry_price"), None)
        if entry is None or entry <= 0 or price <= 0:
            return
        direction = str(state.get("direction") or "up")
        raw_return = (price / entry - 1.0) * 100.0
        directional_return = -raw_return if direction == "down" else raw_return
        state["observations"] = int(state.get("observations", 0)) + 1
        state["last_observed_at"] = now.isoformat()
        state["last_price"] = round(price, 6)
        state["last_directional_return_pct"] = round(directional_return, 4)
        state["mfe_pct"] = round(max(float(state.get("mfe_pct", 0.0)), directional_return), 4)
        state["mae_pct"] = round(min(float(state.get("mae_pct", 0.0)), directional_return), 4)

        created = _parse_time(state.get("signal_time"))
        if created is not None:
            elapsed = (now - created).total_seconds() / 60.0
            checkpoints = state.setdefault("checkpoints", {})
            for label, threshold in CHECKPOINTS_MINUTES.items():
                if elapsed >= threshold and label not in checkpoints:
                    checkpoints[label] = {
                        "observed_at": now.isoformat(),
                        "price": round(price, 6),
                        "directional_return_pct": round(directional_return, 4),
                    }

        if str(state.get("terminal_outcome") or "open") != "open":
            return
        target = _number(state.get("follow_through_target_pct"), 0.0) or 0.0
        stop = _number(state.get("failure_threshold_pct"), 0.0) or 0.0
        if directional_return >= target:
            state["terminal_outcome"] = "success"
            state["terminal_reason"] = "follow_through_target_observed"
            state["terminal_at"] = now.isoformat()
        elif directional_return <= -abs(stop):
            state["terminal_outcome"] = "failed"
            state["terminal_reason"] = "failure_threshold_observed"
            state["terminal_at"] = now.isoformat()

    @staticmethod
    def _active_event(signals: dict[str, Any], symbol: str, now: datetime) -> dict[str, Any] | None:
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for state in signals.values():
            if not isinstance(state, dict) or str(state.get("symbol") or "").upper() != symbol:
                continue
            created = _parse_time(state.get("signal_time"))
            if created is None:
                continue
            age = (now - created).total_seconds()
            if 0 <= age < EVENT_REENTRY_SECONDS:
                candidates.append((created, state))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    @staticmethod
    def _dedupe_existing(signals: dict[str, Any]) -> int:
        """Collapse legacy stage/score duplicates while preserving entry truth.

        The earliest state in a four-hour cluster is canonical. We preserve its
        entry price, stage, score, thresholds and terminal semantics. Later states
        contribute stage history only. This intentionally avoids backfilling a
        terminal result calculated from a later entry price.
        """
        rows: list[tuple[str, datetime, dict[str, Any]]] = []
        for signal_id, state in signals.items():
            if not isinstance(state, dict):
                continue
            created = _parse_time(state.get("signal_time"))
            symbol = str(state.get("symbol") or "").upper().strip()
            if created is not None and symbol:
                rows.append((signal_id, created, state))
        rows.sort(key=lambda item: (str(item[2].get("symbol") or "").upper(), item[1]))

        removed = 0
        last_by_symbol: dict[str, tuple[datetime, dict[str, Any]]] = {}
        for signal_id, created, state in rows:
            symbol = str(state.get("symbol") or "").upper().strip()
            prior = last_by_symbol.get(symbol)
            if prior is None or (created - prior[0]).total_seconds() >= EVENT_REENTRY_SECONDS:
                history = state.setdefault("stage_history", [])
                if not isinstance(history, list):
                    history = []
                    state["stage_history"] = history
                if not history:
                    history.append(_history_item(state))
                last_by_symbol[symbol] = (created, state)
                continue

            canonical = prior[1]
            history = canonical.setdefault("stage_history", [])
            if not isinstance(history, list):
                history = []
                canonical["stage_history"] = history
            if not history:
                history.append(_history_item(canonical))
            duplicate_history = state.get("stage_history") if isinstance(state.get("stage_history"), list) else []
            additions = [item for item in duplicate_history if isinstance(item, dict)] or [_history_item(state)]
            for item in additions:
                last = history[-1] if history and isinstance(history[-1], dict) else {}
                if last.get("stage") != item.get("stage") or last.get("score_band") != item.get("score_band"):
                    history.append(item)
            signals.pop(signal_id, None)
            removed += 1
        return removed

    def update(
        self,
        stocks: list[dict[str, Any]],
        *,
        now: datetime | None = None,
        market_regime: str = "unknown",
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        payload = _read(self.path)
        signals = payload.setdefault("signals", {})
        if not isinstance(signals, dict):
            signals = {}
            payload["signals"] = signals
        removed_duplicates = self._dedupe_existing(signals)

        by_symbol = {
            str(row.get("symbol") or "").upper(): row
            for row in stocks
            if isinstance(row, dict) and str(row.get("symbol") or "").strip()
        }

        for state in signals.values():
            if not isinstance(state, dict):
                continue
            symbol = str(state.get("symbol") or "").upper()
            current = by_symbol.get(symbol)
            price = _number((current or {}).get("price"), None)
            if price is not None:
                self._observe(state, price, now)
                if current is not None:
                    self._append_stage_history(state, current, now)

        for row in stocks:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
            stage = str(row.get("stage") or "").upper()
            price = _number(row.get("price"), None)
            if not symbol or price is None or price <= 0 or stage not in TRACKABLE_STAGES:
                continue
            if self._active_event(signals, symbol, now) is not None:
                continue
            signal_id = self._signal_id(row, now)
            while signal_id in signals:
                signal_id = hashlib.sha256(f"{signal_id}|{len(signals)}".encode("utf-8")).hexdigest()[:20]
            target, stop = STAGE_THRESHOLDS[stage]
            cause_category, cause_tier, official = self._cause_fields(row)
            score = _number(row.get("score"), 0.0) or 0.0
            state = {
                "signal_id": signal_id,
                "signal_time": now.isoformat(),
                "symbol": symbol,
                "direction": self._direction(row),
                "entry_price": round(price, 6),
                "score": round(score, 4),
                "score_band": _band(score),
                "stage": stage,
                "stage_history": [],
                "market_regime": market_regime,
                "cause_category": cause_category,
                "cause_tier": cause_tier,
                "official_cause": official,
                "follow_through_target_pct": target,
                "failure_threshold_pct": stop,
                "observations": 1,
                "last_observed_at": now.isoformat(),
                "last_price": round(price, 6),
                "last_directional_return_pct": 0.0,
                "mfe_pct": 0.0,
                "mae_pct": 0.0,
                "checkpoints": {},
                "terminal_outcome": "open",
                "measurement_basis": "repeated_radar_snapshots",
            }
            state["stage_history"].append(_history_item(state))
            signals[signal_id] = state

        cutoff_seconds = 10 * 24 * 3600
        for signal_id, state in list(signals.items()):
            created = _parse_time((state or {}).get("signal_time")) if isinstance(state, dict) else None
            if created is not None and (now - created).total_seconds() > cutoff_seconds:
                signals.pop(signal_id, None)

        payload["schema_version"] = 2
        payload["updated_at"] = now.isoformat()
        payload["event_dedupe"] = {
            "window_minutes": EVENT_REENTRY_SECONDS // 60,
            "removed_legacy_duplicates_this_run": removed_duplicates,
            "policy": "one_symbol_event_per_4h_preserve_original_entry",
        }
        payload["measurement_note"] = (
            "Snapshot-based follow-through evidence. It cannot reconstruct intrabar order; "
            "therefore it is used for calibration, not executable-fill claims."
        )
        payload["summary"] = self.summary(payload).as_dict()
        _write(self.path, payload)
        return payload

    @staticmethod
    def summary(payload: dict[str, Any]) -> StockOutcomeSummary:
        rows = [row for row in (payload.get("signals") or {}).values() if isinstance(row, dict)]
        matured = [row for row in rows if isinstance(row.get("checkpoints"), dict) and "60m" in row["checkpoints"]]
        return StockOutcomeSummary(
            tracked=len(rows),
            matured_60m=len(matured),
            successes=sum(row.get("terminal_outcome") == "success" for row in matured),
            failures=sum(row.get("terminal_outcome") == "failed" for row in matured),
            open=sum(row.get("terminal_outcome", "open") == "open" for row in rows),
        )
