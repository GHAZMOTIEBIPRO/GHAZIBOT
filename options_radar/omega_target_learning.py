from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pandas as pd

from .hybrid_fetcher import DataFetcher
from .settings import Settings


MIN_GLOBAL_SAMPLE = 100
MIN_TARGET_COHORT = 30
REENTRY_GAP_MINUTES = 240
MAX_ACTIVE_DAYS = 45

HORIZON_MATURITY_SESSIONS = {
    "INTRADAY_1D": 1,
    "SHORT_1_3D": 3,
    "SWING_3_7D": 7,
    "POSITION_1_4W": 20,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


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


def _iso(value: pd.Timestamp | datetime | None) -> str | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.isoformat()


def _target_rows(opportunity: dict[str, Any]) -> list[dict[str, Any]]:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    horizon = opportunity.get("target_horizon") if isinstance(opportunity.get("target_horizon"), dict) else {}
    horizon_rows = {
        str(row.get("target") or "").upper(): row
        for row in horizon.get("targets", [])
        if isinstance(row, dict)
    }
    output: list[dict[str, Any]] = []
    for label in ("T1", "T2", "T3"):
        key = label.lower()
        target = target_map.get(key) if isinstance(target_map.get(key), dict) else {}
        price = _number(target.get("price"))
        if price <= 0:
            continue
        hrow = horizon_rows.get(label, {})
        bucket = str(hrow.get("horizon_bucket") or horizon.get("primary_horizon") or "UNKNOWN")
        output.append(
            {
                "label": label,
                "price": price,
                "horizon_bucket": bucket,
                "estimated_time_ar": hrow.get("estimated_time_ar") or horizon.get("primary_time_ar"),
                "maturity_sessions": int(HORIZON_MATURITY_SESSIONS.get(bucket, 20)),
                "source": target.get("source"),
                "provenance": target.get("provenance"),
            }
        )
    return output


def _event_id(opportunity: dict[str, Any], generated_at: datetime) -> str:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    t1 = target_map.get("t1") if isinstance(target_map.get("t1"), dict) else {}
    key = "|".join(
        [
            str(opportunity.get("symbol") or "").upper(),
            str(opportunity.get("direction") or "").upper(),
            generated_at.date().isoformat(),
            f"{_number(opportunity.get('price')):.4f}",
            f"{_number(t1.get('price')):.4f}",
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _latest_same_setup(
    signals: dict[str, Any],
    *,
    symbol: str,
    direction: str,
    generated_at: datetime,
) -> dict[str, Any] | None:
    latest: tuple[datetime, dict[str, Any]] | None = None
    for row in signals.values():
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        if str(row.get("direction") or "").upper() != direction:
            continue
        signaled = _parse_time(row.get("signal_time"))
        if signaled is None or signaled > generated_at:
            continue
        if (generated_at - signaled).total_seconds() / 60.0 > REENTRY_GAP_MINUTES:
            continue
        if latest is None or signaled > latest[0]:
            latest = (signaled, row)
    return latest[1] if latest else None


def record_target_signals(
    opportunities: Iterable[dict[str, Any]],
    state: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> int:
    current = generated_at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    signals = state.setdefault("signals", {})
    added = 0
    for opportunity in opportunities:
        if not isinstance(opportunity, dict):
            continue
        tier = str(opportunity.get("opportunity_tier") or "").upper()
        direction = str(opportunity.get("direction") or "").upper()
        symbol = str(opportunity.get("symbol") or "").upper().strip()
        target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
        invalidation = target_map.get("invalidation") if isinstance(target_map.get("invalidation"), dict) else {}
        target_rows = _target_rows(opportunity)
        entry = _number(opportunity.get("price"))
        invalidation_price = _number(invalidation.get("price"))

        if tier == "X" or direction not in {"UPSIDE", "DOWNSIDE"}:
            continue
        if not symbol or entry <= 0 or invalidation_price <= 0 or not target_rows:
            continue

        previous = _latest_same_setup(
            signals,
            symbol=symbol,
            direction=direction,
            generated_at=current,
        )
        if previous is not None:
            continue

        signal_id = _event_id(opportunity, current)
        if signal_id in signals:
            continue

        cause = opportunity.get("explosion_cause") if isinstance(opportunity.get("explosion_cause"), dict) else {}
        target_horizon = opportunity.get("target_horizon") if isinstance(opportunity.get("target_horizon"), dict) else {}
        signals[signal_id] = {
            "signal_id": signal_id,
            "signal_time": current.isoformat(),
            "symbol": symbol,
            "direction": direction,
            "entry_price": round(entry, 6),
            "invalidation": round(invalidation_price, 6),
            "opportunity_tier": tier,
            "explosion_rank": _number(opportunity.get("explosion_rank")),
            "explosion_cause": cause.get("primary"),
            "primary_horizon": target_horizon.get("primary_horizon"),
            "targets": {
                row["label"]: {
                    **row,
                    "status": "OPEN",
                    "hit_at": None,
                    "stop_at": None,
                    "ambiguous_at": None,
                    "elapsed_hours_to_hit": None,
                    "sessions_to_hit": None,
                    "sessions_observed": 0,
                    "matured": False,
                }
                for row in target_rows
            },
            "measurement_basis": "underlying_ohlc_path",
            "research_only": True,
        }
        added += 1

    state["updated_at"] = current.isoformat()
    state["schema_version"] = 1
    state["decision_authority"] = False
    return added


def _normalise_bars(bars: pd.DataFrame, start: datetime) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["High", "Low"])
    frame = bars.copy()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    for column in ("High", "Low"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    start_ts = pd.Timestamp(start)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    return frame[frame.index >= start_ts].dropna(subset=["High", "Low"])


def _sessions_observed(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    dates = pd.Index(frame.index.date).unique()
    return int(len(dates))


def _sessions_to(frame: pd.DataFrame, timestamp: pd.Timestamp) -> int:
    if frame.empty:
        return 0
    segment = frame[frame.index <= timestamp]
    return max(1, _sessions_observed(segment))


def _evaluate_target(
    *,
    frame: pd.DataFrame,
    signal_time: datetime,
    direction: str,
    target_price: float,
    invalidation: float,
    maturity_sessions: int,
) -> dict[str, Any]:
    sessions_seen = _sessions_observed(frame)
    target_at: pd.Timestamp | None = None
    stop_at: pd.Timestamp | None = None
    ambiguous_at: pd.Timestamp | None = None

    for timestamp, row in frame.iterrows():
        high = float(row["High"])
        low = float(row["Low"])
        if direction == "DOWNSIDE":
            target_hit = low <= target_price
            stop_hit = high >= invalidation
        else:
            target_hit = high >= target_price
            stop_hit = low <= invalidation

        if target_hit and stop_hit:
            ambiguous_at = timestamp
            break
        if target_hit:
            target_at = timestamp
            break
        if stop_hit:
            stop_at = timestamp
            break

    if ambiguous_at is not None:
        status = "AMBIGUOUS"
        matured = True
    elif target_at is not None:
        status = "HIT"
        matured = True
    elif stop_at is not None:
        status = "FAILED"
        matured = True
    elif sessions_seen >= maturity_sessions:
        status = "MATURED_MISS"
        matured = True
    else:
        status = "OPEN"
        matured = False

    elapsed_hours = None
    sessions_to_hit = None
    if target_at is not None:
        elapsed_hours = max(
            0.0,
            (target_at.to_pydatetime() - signal_time).total_seconds() / 3600.0,
        )
        sessions_to_hit = _sessions_to(frame, target_at)

    return {
        "status": status,
        "hit_at": _iso(target_at),
        "stop_at": _iso(stop_at),
        "ambiguous_at": _iso(ambiguous_at),
        "elapsed_hours_to_hit": round(elapsed_hours, 3) if elapsed_hours is not None else None,
        "sessions_to_hit": sessions_to_hit,
        "sessions_observed": sessions_seen,
        "matured": matured,
    }


def _fetch_underlying_bars(
    fetcher: DataFetcher,
    *,
    symbol: str,
    start: datetime,
    now: datetime,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for interval in ("5m", "1h", "1d"):
        try:
            result = fetcher.fetch_stock_bars(
                symbol,
                start=start,
                end=now,
                interval=interval,
            )
            frame = _normalise_bars(result.data, start)
            attempts.append({"interval": interval, "ok": not frame.empty, "source": result.source})
            if not frame.empty:
                return frame, {"selected_interval": interval, "source": result.source, "attempts": attempts}
        except Exception as exc:
            attempts.append({"interval": interval, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(columns=["High", "Low"]), {"selected_interval": None, "attempts": attempts}


def update_target_outcomes(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    fetcher: DataFetcher | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    market_fetcher = fetcher or DataFetcher(Settings())

    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    for signal in signals.values():
        if not isinstance(signal, dict):
            continue
        signaled = _parse_time(signal.get("signal_time"))
        if signaled is None:
            continue
        age_days = (current - signaled).total_seconds() / 86400.0
        targets = signal.get("targets") if isinstance(signal.get("targets"), dict) else {}
        if age_days > MAX_ACTIVE_DAYS or all(
            isinstance(target, dict) and target.get("matured") is True
            for target in targets.values()
        ):
            continue

        symbol = str(signal.get("symbol") or "").upper()
        frame, audit = _fetch_underlying_bars(
            market_fetcher,
            symbol=symbol,
            start=signaled,
            now=current,
        )
        signal["data_audit"] = audit
        if frame.empty:
            continue

        direction = str(signal.get("direction") or "UPSIDE").upper()
        invalidation = _number(signal.get("invalidation"))
        for label, target in targets.items():
            if not isinstance(target, dict) or target.get("matured") is True:
                continue
            target_price = _number(target.get("price"))
            if target_price <= 0 or invalidation <= 0:
                continue
            result = _evaluate_target(
                frame=frame,
                signal_time=signaled,
                direction=direction,
                target_price=target_price,
                invalidation=invalidation,
                maturity_sessions=max(1, int(_number(target.get("maturity_sessions"), 20))),
            )
            target.update(result)

        signal["last_updated"] = current.isoformat()

    state["updated_at"] = current.isoformat()
    state["summary"] = summarize_target_state(state)
    return state


def _wilson_interval(successes: int, sample: int, z: float = 1.96) -> tuple[float, float] | None:
    if sample <= 0:
        return None
    p = successes / sample
    denominator = 1.0 + z * z / sample
    centre = (p + z * z / (2.0 * sample)) / denominator
    margin = (
        z
        * math.sqrt((p * (1.0 - p) + z * z / (4.0 * sample)) / sample)
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _cohort_stats(rows: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    matured = [row for row in rows if row.get("matured") is True]
    hits = [row for row in matured if row.get("status") == "HIT"]
    ambiguous = [row for row in matured if row.get("status") == "AMBIGUOUS"]
    sample = len(matured)
    successes = len(hits)
    interval = _wilson_interval(successes, sample)
    session_values = [
        int(row["sessions_to_hit"])
        for row in hits
        if row.get("sessions_to_hit") is not None
    ]
    hour_values = [
        float(row["elapsed_hours_to_hit"])
        for row in hits
        if row.get("elapsed_hours_to_hit") is not None
    ]
    eligible = sample >= minimum
    return {
        "sample": sample,
        "hits": successes,
        "misses": sample - successes,
        "ambiguous": len(ambiguous),
        "hit_rate": round(successes / sample, 4) if sample else None,
        "ci95_low": round(interval[0], 4) if interval else None,
        "ci95_high": round(interval[1], 4) if interval else None,
        "median_sessions_to_hit": round(float(median(session_values)), 2) if session_values else None,
        "median_elapsed_hours_to_hit": round(float(median(hour_values)), 2) if hour_values else None,
        "eligible": eligible,
        "minimum_required": minimum,
    }


def build_target_calibration(
    state: dict[str, Any],
    *,
    minimum_global: int = MIN_GLOBAL_SAMPLE,
    minimum_cohort: int = MIN_TARGET_COHORT,
) -> dict[str, Any]:
    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    flattened: list[dict[str, Any]] = []
    for signal in signals.values():
        if not isinstance(signal, dict):
            continue
        targets = signal.get("targets") if isinstance(signal.get("targets"), dict) else {}
        for label, target in targets.items():
            if not isinstance(target, dict):
                continue
            flattened.append(
                {
                    **target,
                    "target": str(label).upper(),
                    "direction": str(signal.get("direction") or "").upper(),
                    "explosion_cause": signal.get("explosion_cause"),
                    "opportunity_tier": signal.get("opportunity_tier"),
                }
            )

    matured_t1 = [
        row for row in flattened
        if row.get("target") == "T1" and row.get("matured") is True
    ]
    global_ready = len(matured_t1) >= minimum_global

    cohorts: dict[str, dict[str, Any]] = {}
    for label in ("T1", "T2", "T3"):
        label_rows = [row for row in flattened if row.get("target") == label]
        for bucket in HORIZON_MATURITY_SESSIONS:
            group = [row for row in label_rows if row.get("horizon_bucket") == bucket]
            stats = _cohort_stats(group, minimum_cohort)
            stats["target"] = label
            stats["horizon_bucket"] = bucket
            stats["probability_available"] = bool(global_ready and stats["eligible"])
            cohorts[f"{label}:{bucket}"] = stats

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global_matured_t1_sample": len(matured_t1),
        "minimum_global_sample": minimum_global,
        "minimum_target_cohort": minimum_cohort,
        "calibration_ready": global_ready,
        "cohorts": cohorts,
        "policy": {
            "probability_requires_global_sample": True,
            "probability_requires_target_horizon_cohort": True,
            "same_bar_target_stop_is_never_a_win": True,
            "matured_miss_is_counted_as_non_hit": True,
            "target_learning_uses_underlying_ohlc_not_option_premium": True,
            "research_only": True,
        },
        "warning": (
            "Historical hit rates are descriptive research evidence, not guaranteed future probabilities. "
            "No probability is exposed until both the global and target/horizon sample gates are met."
        ),
    }


def target_probability(
    calibration: dict[str, Any] | None,
    *,
    target: str,
    horizon_bucket: str,
) -> dict[str, Any] | None:
    if not isinstance(calibration, dict) or calibration.get("calibration_ready") is not True:
        return None
    cohorts = calibration.get("cohorts") if isinstance(calibration.get("cohorts"), dict) else {}
    row = cohorts.get(f"{str(target).upper()}:{str(horizon_bucket)}")
    if not isinstance(row, dict) or row.get("probability_available") is not True:
        return None
    return {
        "historical_hit_rate": row.get("hit_rate"),
        "historical_sample": row.get("sample"),
        "ci95_low": row.get("ci95_low"),
        "ci95_high": row.get("ci95_high"),
        "median_sessions_to_hit": row.get("median_sessions_to_hit"),
        "median_elapsed_hours_to_hit": row.get("median_elapsed_hours_to_hit"),
        "source": "omega_target_calibration",
    }


def summarize_target_state(state: dict[str, Any]) -> dict[str, Any]:
    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    targets = [
        target
        for signal in signals.values()
        if isinstance(signal, dict)
        for target in (
            signal.get("targets", {}).values()
            if isinstance(signal.get("targets"), dict)
            else []
        )
        if isinstance(target, dict)
    ]
    return {
        "signals": len(signals),
        "targets": len(targets),
        "matured_targets": sum(target.get("matured") is True for target in targets),
        "hits": sum(target.get("status") == "HIT" for target in targets),
        "failed": sum(target.get("status") == "FAILED" for target in targets),
        "matured_misses": sum(target.get("status") == "MATURED_MISS" for target in targets),
        "ambiguous": sum(target.get("status") == "AMBIGUOUS" for target in targets),
        "open": sum(target.get("status") == "OPEN" for target in targets),
    }


@dataclass
class OmegaTargetLearning:
    state_path: Path
    calibration_path: Path
    fetcher: DataFetcher | None = None

    def run(
        self,
        opportunities: Iterable[dict[str, Any]],
        *,
        generated_at: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        state = _load(
            self.state_path,
            {
                "schema_version": 1,
                "updated_at": None,
                "signals": {},
                "decision_authority": False,
            },
        )
        added = record_target_signals(opportunities, state, generated_at=generated_at)
        state = update_target_outcomes(state, now=now, fetcher=self.fetcher)
        calibration = build_target_calibration(state)
        _write(self.state_path, state)
        _write(self.calibration_path, calibration)
        return {
            "added": added,
            "state_summary": state.get("summary", {}),
            "calibration": calibration,
        }


def load_target_calibration(path: str | Path) -> dict[str, Any]:
    return _load(path, {})


def load_target_state(path: str | Path) -> dict[str, Any]:
    return _load(path, {})
