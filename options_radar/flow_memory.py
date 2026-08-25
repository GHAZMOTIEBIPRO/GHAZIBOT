from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def contract_key(row: dict[str, Any]) -> str:
    contract = str(row.get("contract_symbol") or "").upper().strip()
    if contract:
        return contract
    direction = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
    return "|".join(
        [
            str(row.get("symbol") or "").upper().strip(),
            direction,
            str(row.get("expiration") or "")[:10],
            str(row.get("strike") or ""),
        ]
    )


def option_mid(row: dict[str, Any]) -> float:
    mid = _num(row.get("mid"))
    if mid > 0:
        return mid
    bid = _num(row.get("bid"))
    ask = _num(row.get("ask"))
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    return max(_num(row.get("last")), 0.0)


def estimated_notional(row: dict[str, Any]) -> float:
    verified = _num(row.get("verified_unusual_total_value"))
    if verified > 0:
        return verified
    return max(_num(row.get("volume")), 0.0) * max(option_mid(row), 0.0) * 100.0


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


def update_flow_memory(
    state: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_history: int = 18,
) -> list[dict[str, Any]]:
    """Attach repeat-flow and premium-acceleration evidence to option rows.

    Option volume is cumulative during a session, so acceleration is calculated from
    incremental contract volume between observations. The notional field is therefore
    explicitly a proxy (delta volume × current mid × 100) unless trade-level UOA premium
    is available. No output claims buy-to-open.
    """

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    session_date = now.date().isoformat()
    memory = state.setdefault("flow_memory", {})
    output: list[dict[str, Any]] = []

    for raw in rows:
        row = dict(raw)
        key = contract_key(row)
        volume = max(0.0, _num(row.get("volume")))
        oi = max(0.0, _num(row.get("open_interest")))
        mid = max(0.0, option_mid(row))
        underlying = max(0.0, _num(row.get("underlying_price")))
        verified_value = max(0.0, _num(row.get("verified_unusual_total_value")))
        verified_prints = max(0.0, _num(row.get("verified_unusual_print_count")))

        record = memory.get(key) if isinstance(memory.get(key), dict) else {}
        history = record.get("history") if isinstance(record.get("history"), list) else []
        previous = history[-1] if history else None
        same_session = isinstance(previous, dict) and previous.get("session_date") == session_date
        volume_delta = 0.0
        notional_delta = 0.0
        verified_premium_delta = 0.0
        minutes = 0.0
        underlying_move_pct = 0.0
        meaningful_repeat = False

        if isinstance(previous, dict):
            previous_at = _parse_time(previous.get("at"))
            if previous_at is not None:
                minutes = max((now - previous_at).total_seconds() / 60.0, 0.0)
            previous_volume = max(0.0, _num(previous.get("volume")))
            if same_session and volume >= previous_volume:
                volume_delta = volume - previous_volume
            previous_verified = max(0.0, _num(previous.get("verified_value")))
            if same_session and verified_value >= previous_verified:
                verified_premium_delta = verified_value - previous_verified
            notional_delta = volume_delta * mid * 100.0
            previous_underlying = max(0.0, _num(previous.get("underlying")))
            if same_session and previous_underlying > 0 and underlying > 0:
                underlying_move_pct = (underlying / previous_underlying - 1.0) * 100.0

            min_contracts = max(20.0, previous_volume * 0.03)
            meaningful_repeat = same_session and (
                volume_delta >= min_contracts
                or verified_premium_delta >= 50_000
                or verified_prints > max(0.0, _num(previous.get("verified_prints")))
            )

        prior_repeat_hits = int(_num(record.get("repeat_hits"))) if same_session else 0
        repeat_hits = prior_repeat_hits + (1 if meaningful_repeat else 0)
        observation_count = int(_num(record.get("observation_count"))) + 1
        velocity = notional_delta / minutes if same_session and minutes > 0 else 0.0
        verified_velocity = verified_premium_delta / minutes if same_session and minutes > 0 else 0.0

        row.update(
            {
                "repeat_flow_hits": repeat_hits,
                "flow_observation_count": observation_count,
                "flow_volume_delta": int(volume_delta),
                "flow_notional_delta_proxy": round(notional_delta, 2),
                "flow_notional_velocity_per_min": round(velocity, 2),
                "verified_premium_delta": round(verified_premium_delta, 2),
                "verified_premium_velocity_per_min": round(verified_velocity, 2),
                "underlying_move_since_observation_pct": round(underlying_move_pct, 4),
                "repeat_flow_confirmed": repeat_hits >= 2,
                "flow_acceleration_strong": (
                    velocity >= 12_500
                    or verified_velocity >= 10_000
                    or verified_premium_delta >= 150_000
                ),
                "premium_acceleration_is_proxy": verified_premium_delta <= 0,
            }
        )

        observation = {
            "at": now.isoformat(),
            "session_date": session_date,
            "volume": volume,
            "oi": oi,
            "mid": mid,
            "underlying": underlying,
            "verified_value": verified_value,
            "verified_prints": verified_prints,
        }
        history = [item for item in history[-max(1, max_history - 1):] if isinstance(item, dict)] + [observation]
        memory[key] = {
            "history": history,
            "repeat_hits": repeat_hits,
            "observation_count": observation_count,
            "last_seen_at": now.isoformat(),
            "last_session_date": session_date,
        }
        output.append(row)

    if len(memory) > 750:
        ordered = sorted(
            memory.items(),
            key=lambda item: str((item[1] or {}).get("last_seen_at") or "") if isinstance(item[1], dict) else "",
            reverse=True,
        )
        state["flow_memory"] = dict(ordered[:500])
    return output


def attach_strike_clusters(
    selected: list[dict[str, Any]],
    universe_contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Measure same-side concentration across nearby strikes for each expiry.

    Clustering is evidence of coordinated interest across a strike ladder, not proof
    that one participant created all trades.
    """

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in universe_contracts:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
        if side == "CALLS":
            side = "CALL"
        if side == "PUTS":
            side = "PUT"
        expiry = str(row.get("expiration") or "")[:10]
        if not symbol or side not in {"CALL", "PUT"} or not expiry:
            continue
        score = _num(row.get("strict_score") or row.get("score"))
        volume = _num(row.get("volume"))
        oi = _num(row.get("open_interest"))
        ratio = _num(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
        if score < 65 or volume < 100 or (oi > 0 and ratio < 0.75):
            continue
        groups.setdefault((symbol, side, expiry), []).append(row)

    output: list[dict[str, Any]] = []
    for raw in selected:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
        expiry = str(row.get("expiration") or "")[:10]
        strike = _num(row.get("strike"))
        spot = _num(row.get("underlying_price"))
        peers = groups.get((symbol, side, expiry), [])
        nearby: list[dict[str, Any]] = []
        tolerance = max(spot * 0.075, strike * 0.075, 1.0)
        for peer in peers:
            peer_strike = _num(peer.get("strike"))
            if peer_strike <= 0 or strike <= 0 or abs(peer_strike - strike) > tolerance:
                continue
            nearby.append(peer)
        distinct = sorted({round(_num(peer.get("strike")), 6) for peer in nearby if _num(peer.get("strike")) > 0})
        total_volume = int(sum(max(0.0, _num(peer.get("volume"))) for peer in nearby))
        total_notional = sum(estimated_notional(peer) for peer in nearby)
        cluster_score = min(
            100.0,
            max(0.0, (len(distinct) - 1) * 22.0 + math.log10(max(total_volume, 1.0)) * 12.0),
        )
        row.update(
            {
                "strike_cluster_count": len(distinct),
                "strike_cluster_strikes": distinct[:8],
                "strike_cluster_volume": total_volume,
                "strike_cluster_notional_proxy": round(total_notional, 2),
                "strike_cluster_score": round(cluster_score, 2),
                "strike_cluster_confirmed": len(distinct) >= 3 and total_volume >= 750,
            }
        )
        output.append(row)
    return output
