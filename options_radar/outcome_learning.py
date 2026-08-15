from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import exchange_calendars as xcals
import pandas as pd

CHECKPOINT_MINUTES: dict[str, int] = {"15m": 15, "30m": 30, "60m": 60}
MAX_LEARNING_ADJUSTMENT = 4.0
SCHEMA_VERSION = 1


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc(value: Any | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_journal(path: Path, events: list[dict[str, Any]], maximum_lines: int = 5000) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    try:
        existing = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (FileNotFoundError, OSError):
        pass
    encoded = [json.dumps(event, ensure_ascii=False, allow_nan=False) for event in events]
    lines = (existing + encoded)[-maximum_lines:]
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_calibration(path: Path | str) -> dict[str, Any]:
    return _load_json(
        Path(path),
        {
            "schema_version": SCHEMA_VERSION,
            "active": False,
            "sample_size": 0,
            "minimum_sample": 0,
            "global": {},
            "features": {},
        },
    )


def _bin_abs_delta(value: float) -> str:
    value = abs(value)
    if value < 0.42:
        return "0.35-0.42"
    if value < 0.50:
        return "0.42-0.50"
    if value < 0.56:
        return "0.50-0.56"
    return "0.56-0.62"


def _bin_dte(value: float) -> str:
    if value <= 20:
        return "7-20"
    if value <= 35:
        return "21-35"
    return "36-60"


def _bin_gamma_alignment(value: float) -> str:
    if value < 0:
        return "negative"
    if value < 0.15:
        return "0.00-0.15"
    return "0.15+"


def _bin_vol_oi(value: float) -> str:
    if value < 1.8:
        return "1.20-1.80"
    if value < 3.0:
        return "1.80-3.00"
    return "3.00+"


def _bin_spread(value: float) -> str:
    if value <= 0.04:
        return "0-4%"
    if value <= 0.07:
        return "4-7%"
    return "7-10%"


FEATURE_BINS = {
    "abs_delta": lambda row: _bin_abs_delta(_number(row.get("delta"))),
    "dte": lambda row: _bin_dte(_number(row.get("dte"))),
    "gamma_alignment": lambda row: _bin_gamma_alignment(_number(row.get("gamma_context_alignment"))),
    "vol_oi": lambda row: _bin_vol_oi(_number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))),
    "spread": lambda row: _bin_spread(_number(row.get("spread_pct"))),
}


def apply_learning_adjustments(
    contracts: list[dict[str, Any]], calibration: dict[str, Any]
) -> list[dict[str, Any]]:
    active = calibration.get("active") is True
    features = calibration.get("features") if isinstance(calibration.get("features"), dict) else {}
    output: list[dict[str, Any]] = []
    for raw in contracts:
        row = dict(raw)
        adjustment = 0.0
        evidence: list[str] = []
        if active:
            for feature, bin_fn in FEATURE_BINS.items():
                label = bin_fn(row)
                stats = features.get(feature, {}).get(label, {}) if isinstance(features.get(feature), dict) else {}
                value = _number(stats.get("adjustment"))
                if value:
                    adjustment += value
                    evidence.append(f"{feature}:{label} {value:+.2f}")
        adjustment = max(-MAX_LEARNING_ADJUSTMENT, min(MAX_LEARNING_ADJUSTMENT, adjustment))
        row["learning_adjustment"] = round(adjustment, 2)
        row["learning_active"] = active
        row["learning_evidence"] = evidence
        row["learning_sample_size"] = int(_number(calibration.get("sample_size")))
        output.append(row)
    return output


def _quote(row: dict[str, Any], *, entry: bool) -> tuple[float, str] | None:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    last = _number(row.get("last"))
    if bid > 0 and ask >= bid and ask > 0:
        return (ask, "ask_to_bid") if entry else (bid, "ask_to_bid")
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
    if mid > 0:
        return mid, "mid_to_mid"
    if last > 0:
        return last, "last_to_last"
    return None


def _signal_id(row: dict[str, Any], created_at: datetime) -> str:
    contract = str(row.get("contract_symbol") or "").upper().replace(" ", "")
    direction = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
    raw = f"{created_at.date().isoformat()}|{contract}|{direction}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _session_close(created_at: datetime) -> datetime | None:
    try:
        cal = xcals.get_calendar("XNYS")
        minute = pd.Timestamp(created_at).floor("min")
        session = cal.minute_to_session(minute, direction="none")
        close = cal.session_close(session)
        return close.to_pydatetime().astimezone(timezone.utc)
    except Exception:
        return None


def _features(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "delta": _number(row.get("delta")),
        "dte": int(_number(row.get("dte"))),
        "gamma_context_alignment": _number(row.get("gamma_context_alignment")),
        "gamma_concentration_pct": _number(row.get("gamma_concentration_pct")),
        "gamma_context": str(row.get("gamma_context") or ""),
        "vol_to_oi_ratio": _number(row.get("vol_to_oi_ratio") or row.get("vol_oi")),
        "spread_pct": _number(row.get("spread_pct")),
        "flow_momentum_score": _number(row.get("flow_momentum_score")),
        "strict_score": _number(row.get("strict_score")),
        "side_consensus_score": _number(row.get("side_consensus_score")),
        "learning_adjustment": _number(row.get("learning_adjustment")),
        "data_quality": _number(row.get("data_quality")),
        "source": str(row.get("source") or ""),
        "freshness_label": str(row.get("freshness_label") or ""),
    }


def _rows_for_tracking(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], float]:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is True:
        rows = payload.get("production_directional_signals") or payload.get("directional_signals") or []
        minimum = _number(os.getenv("OPTIONS_ALERT_MIN_SCORE", "85"), 85.0)
        return "production", [row for row in rows if isinstance(row, dict)], minimum
    rows = payload.get("free_directional_signals") or []
    minimum = _number(os.getenv("OPTIONS_FREE_ALERT_MIN_SCORE", "87"), 87.0)
    return "free", [row for row in rows if isinstance(row, dict)], minimum


def _start_signals(
    payload: dict[str, Any], state: dict[str, Any], now: datetime
) -> tuple[int, list[dict[str, Any]]]:
    mode, rows, minimum = _rows_for_tracking(payload)
    signals = state.setdefault("signals", {})
    events: list[dict[str, Any]] = []
    created = 0
    for row in rows:
        grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
        strict = _number(row.get("strict_score"))
        if grade not in {"A", "A+"} or strict < minimum:
            continue
        contract = str(row.get("contract_symbol") or "").upper().replace(" ", "")
        symbol = str(row.get("symbol") or "").upper().strip()
        direction = str(row.get("direction_label") or row.get("direction") or "").upper()
        quote = _quote(row, entry=True)
        if not contract or not symbol or direction not in {"CALL", "PUT"} or quote is None:
            continue
        signal_id = _signal_id(row, now)
        if signal_id in signals:
            continue
        entry_price, quote_method = quote
        close_at = _session_close(now)
        feature_snapshot = _features(row)
        signals[signal_id] = {
            "signal_id": signal_id,
            "created_at": now.isoformat(),
            "session_date": now.date().isoformat(),
            "session_close_at": close_at.isoformat() if close_at else None,
            "mode": mode,
            "symbol": symbol,
            "direction": direction,
            "contract_symbol": contract,
            "expiration": str(row.get("expiration") or "")[:10],
            "strike": _number(row.get("strike")),
            "entry_price": round(entry_price, 6),
            "entry_quote_method": quote_method,
            "entry_bid": _number(row.get("bid")),
            "entry_ask": _number(row.get("ask")),
            "entry_last": _number(row.get("last")),
            "features": feature_snapshot,
            "checkpoints": {},
            "missed_checkpoints": [],
            "observations": [],
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "status": "open",
        }
        events.append(
            {
                "event": "signal_created",
                "at": now.isoformat(),
                "signal_id": signal_id,
                "symbol": symbol,
                "direction": direction,
                "contract_symbol": contract,
                "entry_price": round(entry_price, 6),
                "quote_method": quote_method,
                "strict_score": strict,
                "features": feature_snapshot,
            }
        )
        created += 1
    return created, events


def _find_contract(chain: pd.DataFrame, contract_symbol: str) -> dict[str, Any] | None:
    if chain is None or chain.empty or "contract_symbol" not in chain:
        return None
    normalized = chain["contract_symbol"].astype(str).str.upper().str.replace(" ", "", regex=False)
    matches = chain[normalized.eq(contract_symbol)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    return {str(key): value for key, value in row.items()}


def _observation(signal: dict[str, Any], row: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    entry = _number(signal.get("entry_price"))
    if entry <= 0:
        return None
    desired = str(signal.get("entry_quote_method") or "")
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    last = _number(row.get("last"))
    if desired == "ask_to_bid" and bid > 0:
        mark, method = bid, "ask_to_bid"
    else:
        quote = _quote(row, entry=False)
        if quote is None:
            return None
        mark, method = quote
    return_pct = (mark / entry - 1.0) * 100.0
    return {
        "at": now.isoformat(),
        "bid": round(bid, 6),
        "ask": round(ask, 6),
        "last": round(last, 6),
        "mark": round(mark, 6),
        "return_pct": round(return_pct, 4),
        "quote_method": method,
        "source": str(row.get("source") or ""),
        "freshness_label": str(row.get("freshness_label") or ""),
        "data_quality": round(_number(row.get("data_quality")), 4),
    }


def _apply_observation(
    signal: dict[str, Any], observation: dict[str, Any], now: datetime
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    observations = signal.setdefault("observations", [])
    if observations:
        last_at = _utc(observations[-1].get("at"))
        if (now - last_at).total_seconds() < 5 * 60:
            return events
    observations.append(observation)
    signal["observations"] = observations[-40:]
    returns = [_number(item.get("return_pct")) for item in signal["observations"]]
    signal["mfe_pct"] = round(max(returns), 4) if returns else 0.0
    signal["mae_pct"] = round(min(returns), 4) if returns else 0.0

    created_at = _utc(signal.get("created_at"))
    age_minutes = (now - created_at).total_seconds() / 60.0
    checkpoints = signal.setdefault("checkpoints", {})
    missed = signal.setdefault("missed_checkpoints", [])
    tolerance = 35.0
    for label, target in CHECKPOINT_MINUTES.items():
        if label in checkpoints or label in missed:
            continue
        if target <= age_minutes <= target + tolerance:
            checkpoints[label] = dict(observation)
            events.append(
                {
                    "event": "checkpoint",
                    "at": now.isoformat(),
                    "signal_id": signal.get("signal_id"),
                    "checkpoint": label,
                    "return_pct": observation.get("return_pct"),
                    "quote_method": observation.get("quote_method"),
                }
            )
        elif age_minutes > target + tolerance:
            missed.append(label)

    close_raw = signal.get("session_close_at")
    if close_raw and "eod" not in checkpoints:
        close_at = _utc(close_raw)
        seconds_to_close = (close_at - now).total_seconds()
        if -5 * 60 <= seconds_to_close <= 25 * 60:
            checkpoints["eod"] = dict(observation)
            events.append(
                {
                    "event": "checkpoint",
                    "at": now.isoformat(),
                    "signal_id": signal.get("signal_id"),
                    "checkpoint": "eod",
                    "return_pct": observation.get("return_pct"),
                    "quote_method": observation.get("quote_method"),
                }
            )
    if "eod" in checkpoints or age_minutes > 24 * 60:
        signal["status"] = "closed"
    return events


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "hit_rate": 0.0, "mean_return_pct": 0.0, "median_return_pct": 0.0}
    return {
        "n": len(values),
        "hit_rate": round(100.0 * sum(value > 0 for value in values) / len(values), 2),
        "mean_return_pct": round(sum(values) / len(values), 4),
        "median_return_pct": round(float(median(values)), 4),
    }


def build_calibration(state: dict[str, Any], minimum_sample: int) -> dict[str, Any]:
    records: list[tuple[dict[str, Any], float]] = []
    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    for signal in signals.values():
        if not isinstance(signal, dict):
            continue
        checkpoint = (signal.get("checkpoints") or {}).get("60m")
        features = signal.get("features") if isinstance(signal.get("features"), dict) else {}
        if not isinstance(checkpoint, dict) or not features:
            continue
        # Only executable ask-to-bid observations train the adaptive layer.
        if checkpoint.get("quote_method") != "ask_to_bid" or signal.get("entry_quote_method") != "ask_to_bid":
            continue
        value = _number(checkpoint.get("return_pct"), float("nan"))
        if math.isfinite(value):
            records.append((features, value))

    returns = [value for _, value in records]
    global_stats = _stats(returns)
    active = len(records) >= minimum_sample
    min_group = max(20, min(40, math.ceil(minimum_sample / 3)))
    feature_output: dict[str, Any] = {}
    global_hit = _number(global_stats.get("hit_rate"))
    global_mean = _number(global_stats.get("mean_return_pct"))

    for feature, bin_fn in FEATURE_BINS.items():
        buckets: dict[str, list[float]] = {}
        for features, value in records:
            buckets.setdefault(bin_fn(features), []).append(value)
        feature_output[feature] = {}
        for label, values in buckets.items():
            stats = _stats(values)
            adjustment = 0.0
            if active and len(values) >= min_group:
                hit_edge = (_number(stats.get("hit_rate")) - global_hit) / 10.0
                return_edge = (_number(stats.get("mean_return_pct")) - global_mean) / 10.0
                raw = 0.6 * hit_edge + 0.4 * return_edge
                shrink = len(values) / (len(values) + 50.0)
                adjustment = max(-1.5, min(1.5, raw * shrink))
            feature_output[feature][label] = {
                **stats,
                "adjustment": round(adjustment, 3),
                "minimum_group_sample": min_group,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active": active,
        "sample_size": len(records),
        "minimum_sample": minimum_sample,
        "training_checkpoint": "60m",
        "training_quote_method": "ask_to_bid",
        "max_total_adjustment": MAX_LEARNING_ADJUSTMENT,
        "global": global_stats,
        "features": feature_output,
        "policy": "Bayesian-shrunk bounded score adjustment; never bypasses hard execution/risk blockers.",
    }


def update_outcome_learning(
    payload: dict[str, Any],
    *,
    settings: Any,
    fetcher: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _utc(now)
    outcome_path = Path(settings.outcome_path)
    journal_path = Path(settings.signal_journal_path)
    calibration_path = Path(settings.calibration_path)
    state = _load_json(
        outcome_path,
        {"schema_version": SCHEMA_VERSION, "updated_at": now.isoformat(), "signals": {}},
    )
    state.setdefault("signals", {})

    created, events = _start_signals(payload, state, now)
    signals = state.get("signals") if isinstance(state.get("signals"), dict) else {}
    max_age_days = int(getattr(settings, "outcome_max_age_days", 60))
    maximum_symbols = max(1, min(20, int(os.getenv("OPTIONS_LEARNING_MAX_SYMBOLS", "12"))))

    pending: dict[str, list[dict[str, Any]]] = {}
    for signal in signals.values():
        if not isinstance(signal, dict) or signal.get("status") == "closed":
            continue
        created_at = _utc(signal.get("created_at"))
        if now - created_at > timedelta(days=max_age_days):
            signal["status"] = "expired_unobserved"
            continue
        symbol = str(signal.get("symbol") or "").upper().strip()
        if symbol:
            pending.setdefault(symbol, []).append(signal)

    observed = 0
    errors: dict[str, str] = {}
    prioritized = sorted(
        pending,
        key=lambda symbol: min(_utc(item.get("created_at")) for item in pending[symbol]),
    )[:maximum_symbols]
    for symbol in prioritized:
        try:
            result = fetcher.fetch_option_chain(
                symbol,
                min_dte=0,
                max_dte=max(90, int(getattr(settings, "max_dte", 60)) + 7),
                apply_guards=False,
            )
            chain = result.data if hasattr(result, "data") else pd.DataFrame()
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        for signal in pending[symbol]:
            contract = str(signal.get("contract_symbol") or "").upper().replace(" ", "")
            row = _find_contract(chain, contract)
            if row is None:
                continue
            observation = _observation(signal, row, now)
            if observation is None:
                continue
            new_events = _apply_observation(signal, observation, now)
            if new_events or not signal.get("observations"):
                observed += 1
            events.extend(new_events)

    state["updated_at"] = now.isoformat()
    _save_json(outcome_path, state)
    _append_journal(journal_path, events)

    calibration = build_calibration(
        state,
        minimum_sample=int(getattr(settings, "calibration_minimum_sample", 100)),
    )
    _save_json(calibration_path, calibration)

    open_count = sum(
        1 for signal in signals.values()
        if isinstance(signal, dict) and signal.get("status") == "open"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "tracked_new": created,
        "open_signals": open_count,
        "symbols_refreshed": len(prioritized),
        "observations_updated": observed,
        "errors": errors,
        "calibration_active": calibration.get("active") is True,
        "calibration_sample_size": int(_number(calibration.get("sample_size"))),
        "calibration_minimum_sample": int(_number(calibration.get("minimum_sample"))),
        "global_60m": calibration.get("global") or {},
        "policy": "Shadow learning only; bounded adjustments activate after minimum OOS samples and cannot bypass hard blockers.",
    }
