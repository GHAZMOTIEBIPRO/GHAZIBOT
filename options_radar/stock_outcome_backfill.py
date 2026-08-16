from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

AUDIT_SCHEMA_VERSION = 1
AUDIT_HORIZON_MINUTES = 24 * 60
MAX_AUDIT_RECORDS = 10_000
CHECKPOINT_MINUTES = {"15m": 15, "60m": 60, "1d": 24 * 60}
CHECKPOINT_MAX_LAG_MINUTES = {"15m": 10, "60m": 15, "1d": 15}
FINAL_AUDIT_STATUSES = frozenset({"success", "failed", "ambiguous", "non_decisive"})


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


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


def _read(path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
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


def _normalise_bars(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    out = frame.copy()
    out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    for column in ("Open", "High", "Low", "Close"):
        if column not in out:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if "Volume" not in out:
        out["Volume"] = 0.0
    return out.dropna(subset=["Open", "High", "Low", "Close"])


def _directional_return(price: float, entry: float, direction: str) -> float:
    raw = (price / entry - 1.0) * 100.0
    return -raw if direction == "down" else raw


def _checkpoint(
    bars: pd.DataFrame,
    *,
    target: datetime,
    entry: float,
    direction: str,
    maximum_lag_minutes: int,
) -> dict[str, Any] | None:
    candidates = bars[bars.index >= pd.Timestamp(target)]
    if candidates.empty:
        return None
    stamp = candidates.index[0]
    row = candidates.iloc[0]
    lag = (stamp.to_pydatetime() - target).total_seconds() / 60.0
    close = _number(row.get("Close"))
    if close is None or close <= 0:
        return None
    return {
        "target_at": target.isoformat(),
        "observed_at": stamp.to_pydatetime().astimezone(timezone.utc).isoformat(),
        "lag_minutes": round(max(0.0, lag), 2),
        "coverage_qualified": 0 <= lag <= maximum_lag_minutes,
        "price": round(close, 6),
        "directional_return_pct": round(_directional_return(close, entry, direction), 4),
        "price_field": "close",
    }


def _touches(
    row: pd.Series,
    *,
    entry: float,
    direction: str,
    target_pct: float,
    stop_pct: float,
) -> tuple[bool, bool]:
    high = _number(row.get("High"))
    low = _number(row.get("Low"))
    if high is None or low is None or high <= 0 or low <= 0:
        return False, False
    if direction == "down":
        target_price = entry * (1.0 - target_pct / 100.0)
        stop_price = entry * (1.0 + abs(stop_pct) / 100.0)
        return low <= target_price, high >= stop_price
    target_price = entry * (1.0 + target_pct / 100.0)
    stop_price = entry * (1.0 - abs(stop_pct) / 100.0)
    return high >= target_price, low <= stop_price


def _excursions(bars: pd.DataFrame, *, entry: float, direction: str) -> tuple[float, float]:
    if bars.empty:
        return 0.0, 0.0
    high = pd.to_numeric(bars["High"], errors="coerce").dropna()
    low = pd.to_numeric(bars["Low"], errors="coerce").dropna()
    if high.empty or low.empty:
        return 0.0, 0.0
    if direction == "down":
        favourable = -((low / entry) - 1.0) * 100.0
        adverse = -((high / entry) - 1.0) * 100.0
    else:
        favourable = ((high / entry) - 1.0) * 100.0
        adverse = ((low / entry) - 1.0) * 100.0
    return round(float(favourable.max()), 4), round(float(adverse.min()), 4)


def _base_record(state: dict[str, Any]) -> dict[str, Any]:
    signal_id = str(state.get("signal_id") or "").strip()
    return {
        "signal_id": signal_id,
        "signal_time": state.get("signal_time"),
        "symbol": str(state.get("symbol") or "").upper(),
        "direction": str(state.get("direction") or "up").lower(),
        "entry_price": state.get("entry_price"),
        "entry_stage": state.get("entry_stage", state.get("stage")),
        "entry_score": state.get("entry_score", state.get("score")),
        "entry_score_band": state.get("entry_score_band", state.get("score_band")),
        "market_regime": state.get("market_regime"),
        "cause_category": state.get("cause_category"),
        "cause_tier": state.get("cause_tier"),
        "official_cause": bool(state.get("official_cause")),
        "follow_through_target_pct": state.get("follow_through_target_pct"),
        "failure_threshold_pct": state.get("failure_threshold_pct"),
        "snapshot_terminal_outcome": state.get("terminal_outcome", "open"),
        "snapshot_terminal_reason": state.get("terminal_reason"),
        "snapshot_terminal_at": state.get("terminal_at"),
        "audit_status": "pending",
        "audit_source": "yahoo/yfinance historical 5m research fallback",
        "audit_interval": "5m",
        "decision_authority": False,
    }


def evaluate_stock_event_from_bars(
    state: dict[str, Any],
    bars: pd.DataFrame,
    *,
    now: datetime | None = None,
    source: str = "yahoo/yfinance",
) -> dict[str, Any]:
    """Audit one stock event from post-signal 5-minute OHLC bars.

    Bars whose timestamp precedes the signal are excluded to avoid using price
    action that happened before the alert. If both target and stop are inside the
    same 5-minute bar, ordering is unknowable and the result is AMBIGUOUS.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    record = _base_record(state)
    created = _parse_time(state.get("signal_time"))
    entry = _number(state.get("entry_price"))
    target_pct = _number(state.get("follow_through_target_pct"), 0.0) or 0.0
    stop_pct = _number(state.get("failure_threshold_pct"), 0.0) or 0.0
    direction = str(state.get("direction") or "up").lower()
    if created is None or entry is None or entry <= 0 or target_pct <= 0 or stop_pct <= 0:
        record.update(
            {
                "audit_status": "unavailable",
                "audit_reason": "invalid_signal_metadata",
                "audited_at": current.isoformat(),
            }
        )
        return record

    frame = _normalise_bars(bars)
    if frame.empty:
        record.update(
            {
                "audit_status": "unavailable",
                "audit_reason": "no_post_signal_5m_bars",
                "audited_at": current.isoformat(),
            }
        )
        return record
    frame = frame[frame.index >= pd.Timestamp(created)]
    if frame.empty:
        record.update(
            {
                "audit_status": "unavailable",
                "audit_reason": "no_post_signal_5m_bars",
                "audited_at": current.isoformat(),
            }
        )
        return record

    checkpoints: dict[str, Any] = {}
    for label, minutes in CHECKPOINT_MINUTES.items():
        checkpoint = _checkpoint(
            frame,
            target=created + timedelta(minutes=minutes),
            entry=entry,
            direction=direction,
            maximum_lag_minutes=CHECKPOINT_MAX_LAG_MINUTES[label],
        )
        if checkpoint is not None:
            checkpoints[label] = checkpoint

    horizon_target = created + timedelta(minutes=AUDIT_HORIZON_MINUTES)
    one_day = checkpoints.get("1d") if isinstance(checkpoints.get("1d"), dict) else None
    qualified_1d = bool(one_day and one_day.get("coverage_qualified") is True)
    # Never scan materially beyond the one-day horizon. A qualified 1d bar may
    # start a few minutes after the exact target time, so only that strict
    # tolerance is permitted; weekend/overnight gaps remain pending.
    if qualified_1d:
        horizon_end = pd.Timestamp(one_day["observed_at"])
    else:
        horizon_end = pd.Timestamp(min(current, horizon_target))
    horizon = frame[frame.index <= horizon_end]

    terminal_status = "pending"
    terminal_reason = "one_day_horizon_not_complete"
    terminal_at: str | None = None
    terminal_bar: dict[str, Any] | None = None
    for stamp, row in horizon.iterrows():
        target_touch, stop_touch = _touches(
            row,
            entry=entry,
            direction=direction,
            target_pct=target_pct,
            stop_pct=stop_pct,
        )
        if not target_touch and not stop_touch:
            continue
        terminal_at = stamp.to_pydatetime().astimezone(timezone.utc).isoformat()
        terminal_bar = {
            "open": round(float(row["Open"]), 6),
            "high": round(float(row["High"]), 6),
            "low": round(float(row["Low"]), 6),
            "close": round(float(row["Close"]), 6),
        }
        if target_touch and stop_touch:
            terminal_status = "ambiguous"
            terminal_reason = "target_and_stop_touched_same_5m_bar_order_unknown"
        elif target_touch:
            terminal_status = "success"
            terminal_reason = "target_touched_first_in_observed_5m_sequence"
        else:
            terminal_status = "failed"
            terminal_reason = "stop_touched_first_in_observed_5m_sequence"
        break

    if terminal_status == "pending" and qualified_1d:
        terminal_status = "non_decisive"
        terminal_reason = "no_target_or_stop_touch_through_qualified_1d_checkpoint"

    mfe, mae = _excursions(horizon, entry=entry, direction=direction)
    snapshot_outcome = str(state.get("terminal_outcome") or "open")
    discrepancy = (
        snapshot_outcome in {"success", "failed"}
        and terminal_status in {"success", "failed"}
        and snapshot_outcome != terminal_status
    )
    record.update(
        {
            "audit_status": terminal_status,
            "audit_reason": terminal_reason,
            "audit_terminal_at": terminal_at,
            "audit_terminal_bar": terminal_bar,
            "audit_source": source,
            "audited_at": current.isoformat(),
            "checkpoints": checkpoints,
            "coverage": {
                label: bool(
                    isinstance(checkpoints.get(label), dict)
                    and checkpoints[label].get("coverage_qualified") is True
                )
                for label in CHECKPOINT_MINUTES
            },
            "audit_mfe_pct": mfe,
            "audit_mae_pct": mae,
            "snapshot_discrepancy": discrepancy,
            "measurement_policy": {
                "checkpoint_price": "first 5m close at/after target time within tolerance",
                "terminal_touch": "chronological 5m high/low touch",
                "same_bar_target_stop": "ambiguous",
                "pre_signal_bar_excluded": True,
                "intrabar_order_claimed": False,
                "one_day_max_lag_minutes": CHECKPOINT_MAX_LAG_MINUTES["1d"],
            },
        }
    )
    return record


@dataclass(frozen=True)
class StockAuditCoverage:
    records: int
    covered_15m: int
    covered_60m: int
    covered_1d: int
    decisive: int
    ambiguous: int
    non_decisive: int
    pending: int
    unavailable: int
    discrepancies: int

    def as_dict(self) -> dict[str, Any]:
        denominator = max(1, self.records)
        return {
            "records": self.records,
            "covered_15m": self.covered_15m,
            "covered_60m": self.covered_60m,
            "covered_1d": self.covered_1d,
            "coverage_15m_pct": round(100.0 * self.covered_15m / denominator, 2),
            "coverage_60m_pct": round(100.0 * self.covered_60m / denominator, 2),
            "coverage_1d_pct": round(100.0 * self.covered_1d / denominator, 2),
            "decisive": self.decisive,
            "ambiguous": self.ambiguous,
            "non_decisive": self.non_decisive,
            "pending": self.pending,
            "unavailable": self.unavailable,
            "snapshot_discrepancies": self.discrepancies,
        }


def coverage_summary(records: dict[str, dict[str, Any]]) -> StockAuditCoverage:
    rows = [row for row in records.values() if isinstance(row, dict)]

    def covered(label: str) -> int:
        return sum(bool((row.get("coverage") or {}).get(label)) for row in rows)

    return StockAuditCoverage(
        records=len(rows),
        covered_15m=covered("15m"),
        covered_60m=covered("60m"),
        covered_1d=covered("1d"),
        decisive=sum(row.get("audit_status") in {"success", "failed"} for row in rows),
        ambiguous=sum(row.get("audit_status") == "ambiguous" for row in rows),
        non_decisive=sum(row.get("audit_status") == "non_decisive" for row in rows),
        pending=sum(row.get("audit_status") == "pending" for row in rows),
        unavailable=sum(row.get("audit_status") == "unavailable" for row in rows),
        discrepancies=sum(row.get("snapshot_discrepancy") is True for row in rows),
    )


class StockOutcomeBackfillAuditor:
    def __init__(self, audit_path: str | Path, *, maximum_records: int = MAX_AUDIT_RECORDS):
        self.audit_path = Path(audit_path)
        self.maximum_records = max(100, int(maximum_records))

    def load(self) -> dict[str, Any]:
        return _read(
            self.audit_path,
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "records": {},
            },
        )

    def seed_events(self, stock_outcomes: dict[str, Any]) -> dict[str, Any]:
        audit = self.load()
        records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
        signals = stock_outcomes.get("signals") if isinstance(stock_outcomes.get("signals"), dict) else {}
        for key, state in signals.items():
            if not isinstance(state, dict):
                continue
            signal_id = str(state.get("signal_id") or key).strip()
            if not signal_id:
                continue
            previous = records.get(signal_id) if isinstance(records.get(signal_id), dict) else {}
            base = _base_record({**state, "signal_id": signal_id})
            records[signal_id] = {**base, **previous}
            # Snapshot evidence may improve while audit evidence stays immutable.
            records[signal_id]["snapshot_terminal_outcome"] = state.get("terminal_outcome", "open")
            records[signal_id]["snapshot_terminal_reason"] = state.get("terminal_reason")
            records[signal_id]["snapshot_terminal_at"] = state.get("terminal_at")

        if len(records) > self.maximum_records:
            ordered = sorted(
                records.items(),
                key=lambda item: _parse_time(item[1].get("signal_time"))
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )[: self.maximum_records]
            records = dict(ordered)
        audit["records"] = records
        return audit

    @staticmethod
    def symbols_needing_backfill(
        audit: dict[str, Any],
        *,
        now: datetime,
        maximum_symbols: int,
    ) -> list[str]:
        records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
        candidates: dict[str, datetime] = {}
        for row in records.values():
            if not isinstance(row, dict):
                continue
            status = str(row.get("audit_status") or "pending")
            coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
            if status in FINAL_AUDIT_STATUSES and coverage.get("1d") is True:
                continue
            created = _parse_time(row.get("signal_time"))
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol or created is None or now < created + timedelta(minutes=15):
                continue
            if symbol not in candidates or created < candidates[symbol]:
                candidates[symbol] = created
        ordered = sorted(candidates, key=lambda symbol: (candidates[symbol], symbol))
        return ordered[: max(1, int(maximum_symbols))]

    def apply_symbol_bars(
        self,
        audit: dict[str, Any],
        *,
        symbol: str,
        bars: pd.DataFrame,
        now: datetime,
        source: str,
    ) -> int:
        records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
        updated = 0
        for signal_id, row in list(records.items()):
            if not isinstance(row, dict) or str(row.get("symbol") or "").upper() != symbol.upper():
                continue
            status = str(row.get("audit_status") or "pending")
            coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
            if status in FINAL_AUDIT_STATUSES and coverage.get("1d") is True:
                continue
            evaluated = evaluate_stock_event_from_bars(row, bars, now=now, source=source)
            # Preserve the latest snapshot fields already seeded from live state.
            for key in ("snapshot_terminal_outcome", "snapshot_terminal_reason", "snapshot_terminal_at"):
                if key in row:
                    evaluated[key] = row[key]
            snapshot = str(evaluated.get("snapshot_terminal_outcome") or "open")
            audited = str(evaluated.get("audit_status") or "pending")
            evaluated["snapshot_discrepancy"] = (
                snapshot in {"success", "failed"}
                and audited in {"success", "failed"}
                and snapshot != audited
            )
            records[signal_id] = evaluated
            updated += 1
        audit["records"] = records
        return updated

    def finalise(
        self,
        audit: dict[str, Any],
        *,
        now: datetime,
        attempted_symbols: int,
        errors: dict[str, str],
    ) -> dict[str, Any]:
        records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
        coverage = coverage_summary(records)
        audit.update(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "updated_at": now.astimezone(timezone.utc).isoformat(),
                "mode": "HISTORICAL_5M_OUTCOME_AUDIT",
                "decision_authority": False,
                "live_alert_weights_changed": False,
                "provider_policy": "free research fallback only; no paid provider required",
                "source_policy": "Yahoo/YFinance historical 5m is unofficial research data, never live alert authority",
                "coverage": coverage.as_dict(),
                "attempted_symbols_this_pass": attempted_symbols,
                "errors": errors,
                "promotion_gate": {
                    "minimum_60m_coverage_pct": 90.0,
                    "minimum_independent_sessions": 10,
                    # The runner must add the independent-session count before
                    # coverage can be declared ready. Direct module use is fail-closed.
                    "coverage_ready": False,
                    "independent_session_gate_pending": True,
                    "walk_forward_required_after_coverage": True,
                    "live_promotion_allowed": False,
                },
            }
        )
        _write(self.audit_path, audit)
        return audit
