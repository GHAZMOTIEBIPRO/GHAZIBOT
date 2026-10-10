from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from statistics import median
from typing import Any

import exchange_calendars as xcals
import pandas as pd

CHECKPOINT_MINUTES = {"15m": 15, "60m": 60}
MIN_REVIEW_PAIRS = 100
MIN_REVIEW_SESSIONS = 20


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
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _contract_key(value: Any) -> str:
    return str(value or "").replace(" ", "").upper()


def _quote_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = row.get("quote_timestamp")
    if not raw:
        kind = str(row.get("timestamp_kind") or "").strip().lower()
        if kind in {"quote", "provider_quote", "quote_snapshot"}:
            raw = row.get("updated_at")
    if not raw:
        return None
    try:
        return _utc(raw)
    except (TypeError, ValueError):
        return None


def _quote_valid(
    row: dict[str, Any],
    *,
    now: datetime,
    max_age_minutes: float,
) -> bool:
    stamp = _quote_timestamp(row)
    if stamp is None:
        return False
    age = (now - stamp).total_seconds() / 60.0
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    source = str(row.get("source") or "").strip()
    return bool(
        0 <= age <= max_age_minutes
        and bid > 0
        and ask > bid
        and source
    )


def _entry_mark(row: dict[str, Any]) -> float:
    ask = _number(row.get("ask"))
    return ask if ask > 0 else 0.0


def _exit_mark(row: dict[str, Any]) -> float:
    bid = _number(row.get("bid"))
    return bid if bid > 0 else 0.0


def _chain_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    radar = (
        payload.get("expiry_radar")
        if isinstance(payload.get("expiry_radar"), dict)
        else {}
    )
    tabs = radar.get("tabs") if isinstance(radar.get("tabs"), dict) else {}
    all_exp = (
        tabs.get("all_expirations")
        if isinstance(tabs.get("all_expirations"), dict)
        else {}
    )
    output: dict[str, dict[str, Any]] = {}
    for side in ("calls", "puts"):
        rows = all_exp.get(side) if isinstance(all_exp.get(side), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = _contract_key(row.get("contract_symbol"))
            if key:
                output[key] = row
    return output


def _intelligence_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    intelligence = (
        payload.get("option_contract_intelligence")
        if isinstance(payload.get("option_contract_intelligence"), dict)
        else {}
    )
    by_symbol = (
        intelligence.get("by_symbol")
        if isinstance(intelligence.get("by_symbol"), dict)
        else {}
    )
    return {
        str(symbol).upper(): row
        for symbol, row in by_symbol.items()
        if isinstance(row, dict)
    }


def _response_score(row: dict[str, Any]) -> float | None:
    grade = (
        row.get("underlying_response_grade")
        if isinstance(row.get("underlying_response_grade"), dict)
        else {}
    )
    value = _number(grade.get("score"), float("nan"))
    return round(value, 4) if math.isfinite(value) else None


def _pair_id(symbol: str, now: datetime) -> str:
    # Freeze the first eligible A/B pair for each symbol/session. Contract
    # changes later in the same day must not create extra samples.
    raw = f"{now.date().isoformat()}|{symbol.upper()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _session_close(now: datetime) -> datetime | None:
    try:
        cal = xcals.get_calendar("XNYS")
        minute = pd.Timestamp(now).floor("min")
        session = cal.minute_to_session(minute, direction="none")
        return cal.session_close(session).to_pydatetime().astimezone(timezone.utc)
    except Exception:
        return None


def _checkpoint_due(
    created: datetime,
    now: datetime,
    checkpoints: dict[str, Any],
) -> str | None:
    elapsed = (now - created).total_seconds() / 60.0
    # Prefer the latest due checkpoint. If a run skips the 15m window and
    # lands exactly around 60m, that observation belongs to 60m rather than
    # consuming the older checkpoint and losing the more informative horizon.
    for label, target in sorted(
        CHECKPOINT_MINUTES.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        if label in checkpoints:
            continue
        if target <= elapsed <= target + 45:
            return label
    return None


def _pair_observation(
    pair: dict[str, Any],
    chain: dict[str, dict[str, Any]],
    *,
    now: datetime,
    max_age_minutes: float,
) -> dict[str, Any] | None:
    primary_key = _contract_key(pair.get("primary_contract"))
    shadow_key = _contract_key(pair.get("shadow_contract"))
    primary = chain.get(primary_key)
    shadow = chain.get(shadow_key)
    if not isinstance(primary, dict) or not isinstance(shadow, dict):
        return None
    if not _quote_valid(primary, now=now, max_age_minutes=max_age_minutes):
        return None
    if not _quote_valid(shadow, now=now, max_age_minutes=max_age_minutes):
        return None

    primary_entry = _number(pair.get("primary_entry_ask"))
    shadow_entry = _number(pair.get("shadow_entry_ask"))
    primary_exit = _exit_mark(primary)
    shadow_exit = _exit_mark(shadow)
    if min(primary_entry, shadow_entry, primary_exit, shadow_exit) <= 0:
        return None

    primary_return = (primary_exit / primary_entry - 1.0) * 100.0
    shadow_return = (shadow_exit / shadow_entry - 1.0) * 100.0
    return {
        "at": now.isoformat(),
        "primary_bid": round(primary_exit, 6),
        "shadow_bid": round(shadow_exit, 6),
        "primary_return_pct": round(primary_return, 4),
        "shadow_return_pct": round(shadow_return, 4),
        "shadow_minus_primary_pct": round(shadow_return - primary_return, 4),
        "primary_source": str(primary.get("source") or ""),
        "shadow_source": str(shadow.get("source") or ""),
        "quote_basis": "simultaneous ask-entry / bid-exit research comparison",
        "execution_claim": False,
    }


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean_shadow_minus_primary_pct": 0.0,
            "median_shadow_minus_primary_pct": 0.0,
            "shadow_win_rate_pct": 0.0,
            "primary_win_rate_pct": 0.0,
            "tie_rate_pct": 0.0,
        }
    tolerance = 0.05
    shadow_wins = sum(value > tolerance for value in values)
    primary_wins = sum(value < -tolerance for value in values)
    ties = len(values) - shadow_wins - primary_wins
    return {
        "n": len(values),
        "mean_shadow_minus_primary_pct": round(sum(values) / len(values), 4),
        "median_shadow_minus_primary_pct": round(float(median(values)), 4),
        "shadow_win_rate_pct": round(100.0 * shadow_wins / len(values), 2),
        "primary_win_rate_pct": round(100.0 * primary_wins / len(values), 2),
        "tie_rate_pct": round(100.0 * ties / len(values), 2),
    }


def _report(
    pairs: dict[str, Any],
    *,
    same_choice_symbols: int,
    now: datetime,
) -> dict[str, Any]:
    rows = [row for row in pairs.values() if isinstance(row, dict)]
    checkpoint_values: dict[str, list[float]] = {
        label: [] for label in (*CHECKPOINT_MINUTES, "eod")
    }
    sessions_60m: set[str] = set()
    for row in rows:
        checkpoints = (
            row.get("checkpoints")
            if isinstance(row.get("checkpoints"), dict)
            else {}
        )
        for label in checkpoint_values:
            value = checkpoints.get(label)
            if not isinstance(value, dict):
                continue
            delta = _number(value.get("shadow_minus_primary_pct"), float("nan"))
            if math.isfinite(delta):
                checkpoint_values[label].append(delta)
                if label == "60m":
                    sessions_60m.add(str(row.get("session_date") or ""))

    stats = {label: _stats(values) for label, values in checkpoint_values.items()}
    mature = stats["60m"]
    evidence_ready = bool(
        mature["n"] >= MIN_REVIEW_PAIRS
        and len({value for value in sessions_60m if value}) >= MIN_REVIEW_SESSIONS
        and mature["mean_shadow_minus_primary_pct"] > 0
        and mature["median_shadow_minus_primary_pct"] > 0
        and mature["shadow_win_rate_pct"] > mature["primary_win_rate_pct"]
    )
    return {
        "version": "RESPONSE_SHADOW_AB_V1",
        "generated_at": now.isoformat(),
        "tracked_pairs": len(rows),
        "open_pairs": sum(str(row.get("status") or "") == "open" for row in rows),
        "valid_entry_pairs": sum(row.get("entry_verified") is True for row in rows),
        "same_choice_symbols_current_run": same_choice_symbols,
        "independent_60m_sessions": len(
            {value for value in sessions_60m if value}
        ),
        "checkpoints": stats,
        "promotion_gate": {
            "minimum_60m_pairs": MIN_REVIEW_PAIRS,
            "minimum_independent_sessions": MIN_REVIEW_SESSIONS,
            "evidence_ready_for_manual_review": evidence_ready,
            "live_promotion_allowed": False,
            "manual_review_required": True,
            "out_of_sample_or_forward_collection_required": True,
        },
        "policy": {
            "research_only": True,
            "decision_authority": False,
            "same_session_first_pair_only": True,
            "entry_basis": "simultaneous fresh two-sided ask",
            "exit_basis": "simultaneous fresh two-sided bid",
            "stale_or_unstamped_quotes_excluded": True,
            "response_score_is_not_probability": True,
            "v11_unchanged": True,
        },
    }


def update_response_shadow_ab(
    payload: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_quote_age_minutes: float = 120.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Forward-track Primary vs Response Shadow on the exact same timestamps.

    This is research attribution only. It can never alter the selected primary,
    V11, Telegram delivery, or live scoring.
    """

    now = _utc(now)
    state = state if isinstance(state, dict) else {}
    pairs = state.get("pairs") if isinstance(state.get("pairs"), dict) else {}
    chain = _chain_rows(payload)
    intelligence = _intelligence_rows(payload)
    same_choice_symbols = 0

    for symbol, item in intelligence.items():
        primary = item.get("primary") if isinstance(item.get("primary"), dict) else {}
        shadow = (
            item.get("response_shadow_best")
            if isinstance(item.get("response_shadow_best"), dict)
            else {}
        )
        primary_contract = _contract_key(primary.get("contract_symbol"))
        shadow_contract = _contract_key(shadow.get("contract_symbol"))
        if not primary_contract or not shadow_contract:
            continue
        if primary_contract == shadow_contract:
            same_choice_symbols += 1
            continue

        pair_id = _pair_id(symbol, now)
        if pair_id in pairs:
            continue

        primary_row = chain.get(primary_contract, primary)
        shadow_row = chain.get(shadow_contract, shadow)
        if not _quote_valid(
            primary_row,
            now=now,
            max_age_minutes=max_quote_age_minutes,
        ) or not _quote_valid(
            shadow_row,
            now=now,
            max_age_minutes=max_quote_age_minutes,
        ):
            continue

        primary_entry = _entry_mark(primary_row)
        shadow_entry = _entry_mark(shadow_row)
        if min(primary_entry, shadow_entry) <= 0:
            continue

        close = _session_close(now)
        pairs[pair_id] = {
            "pair_id": pair_id,
            "created_at": now.isoformat(),
            "session_date": now.date().isoformat(),
            "session_close_at": close.isoformat() if close else None,
            "symbol": symbol,
            "side": str(primary.get("side") or "").upper(),
            "primary_contract": primary_contract,
            "shadow_contract": shadow_contract,
            "primary_response_score": _response_score(primary),
            "shadow_response_score": _response_score(shadow),
            "primary_entry_ask": round(primary_entry, 6),
            "shadow_entry_ask": round(shadow_entry, 6),
            "primary_entry_source": str(primary_row.get("source") or ""),
            "shadow_entry_source": str(shadow_row.get("source") or ""),
            "entry_verified": True,
            "checkpoints": {},
            "observations": [],
            "status": "open",
            "research_only": True,
            "decision_authority": False,
        }

    for pair in pairs.values():
        if not isinstance(pair, dict) or str(pair.get("status") or "") != "open":
            continue
        observation = _pair_observation(
            pair,
            chain,
            now=now,
            max_age_minutes=max_quote_age_minutes,
        )
        if observation is None:
            continue

        observations = (
            pair.get("observations")
            if isinstance(pair.get("observations"), list)
            else []
        )
        if observations:
            try:
                last_at = _utc(observations[-1].get("at"))
            except (TypeError, ValueError):
                last_at = None
            if last_at is not None and (now - last_at).total_seconds() < 5 * 60:
                continue
        observations.append(observation)
        pair["observations"] = observations[-80:]

        checkpoints = (
            pair.get("checkpoints")
            if isinstance(pair.get("checkpoints"), dict)
            else {}
        )
        created = _utc(pair.get("created_at"))
        label = _checkpoint_due(created, now, checkpoints)
        if label:
            checkpoints[label] = dict(observation)

        close_raw = pair.get("session_close_at")
        if close_raw and "eod" not in checkpoints:
            close = _utc(close_raw)
            seconds = (close - now).total_seconds()
            if -5 * 60 <= seconds <= 25 * 60:
                checkpoints["eod"] = dict(observation)

        pair["checkpoints"] = checkpoints
        pair["last_observed_at"] = now.isoformat()
        pair["last_shadow_minus_primary_pct"] = observation[
            "shadow_minus_primary_pct"
        ]
        if "eod" in checkpoints or (now - created).total_seconds() > 24 * 3600:
            pair["status"] = "closed"

    # Keep enough history for forward evidence while bounding durable state.
    ordered = sorted(
        (
            row
            for row in pairs.values()
            if isinstance(row, dict)
        ),
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )[:2000]
    bounded_pairs = {
        str(row.get("pair_id")): row
        for row in ordered
        if str(row.get("pair_id") or "")
    }
    report = _report(
        bounded_pairs,
        same_choice_symbols=same_choice_symbols,
        now=now,
    )
    state_out = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "pairs": bounded_pairs,
        "decision_authority": False,
        "research_only": True,
    }
    return report, state_out
