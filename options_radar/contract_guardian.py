from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from .guardian_research import (
    catalyst_report_ar,
    chart_risk_context,
    record_option_quote_snapshot,
    record_unstamped_research_observation,
)


TERMINAL_STAGES = {"T3_HIT", "INVALIDATED", "EXPIRED"}


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


def _contract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    radar = payload.get("expiry_radar") if isinstance(payload.get("expiry_radar"), dict) else {}
    tabs = radar.get("tabs") if isinstance(radar.get("tabs"), dict) else {}
    all_exp = tabs.get("all_expirations") if isinstance(tabs.get("all_expirations"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("calls", "puts"):
        values = all_exp.get(key) if isinstance(all_exp.get(key), list) else []
        rows.extend(dict(row) for row in values if isinstance(row, dict))
    return rows


def _selected(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
    selected: dict[str, dict[str, Any]] = {}
    for symbol, item in by_symbol.items():
        if not isinstance(item, dict):
            continue
        primary = item.get("primary") if isinstance(item.get("primary"), dict) else {}
        contract = str(primary.get("contract_symbol") or "").replace(" ", "").upper()
        stage = str(primary.get("alert_stage") or "NONE").upper()
        if contract and stage in {"WATCH", "CONFIRMED"}:
            selected[contract] = {
                "symbol": str(symbol).upper(),
                "item": item,
                "primary": primary,
            }
    return selected


def _stock_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in payload.get("stocks", []) or []
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _opportunity_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    rows = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _catalyst_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intel = (
        omega.get("catalyst_intelligence")
        if isinstance(omega.get("catalyst_intelligence"), dict)
        else {}
    )
    by_symbol = intel.get("by_symbol") if isinstance(intel.get("by_symbol"), dict) else {}
    return {
        str(symbol).upper(): row
        for symbol, row in by_symbol.items()
        if isinstance(row, dict)
    }


def _mark(row: dict[str, Any], *, entry: bool = False) -> tuple[float, str]:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    mid = _number(row.get("mid"))
    last = _number(row.get("last"))
    if entry and ask > 0:
        return ask, "ask"
    if not entry and bid > 0:
        return bid, "bid"
    if mid > 0:
        return mid, "mid"
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0, "mid"
    if last > 0:
        return last, "last"
    return max(bid, ask, 0.0), "unavailable"


def _target_map(stock: dict[str, Any], opportunity: dict[str, Any]) -> dict[str, Any]:
    mapped = opportunity.get("target_map")
    if isinstance(mapped, dict):
        return mapped
    return {
        "entry": {
            "low": _number(stock.get("entry_low")),
            "high": _number(stock.get("entry_high")),
        },
        "invalidation": {
            "price": _number(stock.get("invalidation"), _number(stock.get("stop"))),
        },
        "t1": {"price": _number(stock.get("target_1"))},
        "t2": {"price": _number(stock.get("target_2"))},
        "t3": {"price": _number(stock.get("target_3"))},
    }


def _target_price(target_map: dict[str, Any], key: str) -> float:
    row = target_map.get(key)
    return _number(row.get("price")) if isinstance(row, dict) else 0.0


def _entry_zone(target_map: dict[str, Any], stock: dict[str, Any]) -> tuple[float, float]:
    row = target_map.get("entry") if isinstance(target_map.get("entry"), dict) else {}
    low = _number(row.get("low"), _number(stock.get("entry_low")))
    high = _number(row.get("high"), _number(stock.get("entry_high")))
    if low > 0 and high > 0:
        return min(low, high), max(low, high)
    price = _number(stock.get("price"))
    return price, price


def _hit(side: str, spot: float, target: float) -> bool:
    if spot <= 0 or target <= 0:
        return False
    return spot >= target if side == "CALL" else spot <= target


def _invalidated(side: str, spot: float, invalidation: float) -> bool:
    if spot <= 0 or invalidation <= 0:
        return False
    return spot <= invalidation if side == "CALL" else spot >= invalidation


def _quote_age_minutes(row: dict[str, Any], now: datetime) -> float | None:
    raw = row.get("quote_timestamp")
    if not raw:
        kind = str(row.get("timestamp_kind") or "").lower()
        if kind in {"", "quote", "provider_quote", "quote_snapshot"}:
            raw = row.get("updated_at")
    if not raw:
        return None
    try:
        stamp = _utc(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, (now - stamp).total_seconds() / 60.0)


def _expiration_passed(value: Any, now: datetime) -> bool:
    text = str(value or "")[:10]
    if not text:
        return False
    try:
        expiry = date.fromisoformat(text)
    except ValueError:
        return False
    return expiry < now.date()


def _state_stage(
    *,
    side: str,
    spot: float,
    target_map: dict[str, Any],
    alert_stage: str,
    expiration: Any,
    now: datetime,
) -> str:
    if _expiration_passed(expiration, now):
        return "EXPIRED"

    invalidation = _target_price(target_map, "invalidation")
    if _invalidated(side, spot, invalidation):
        return "INVALIDATED"

    for label in ("t3", "t2", "t1"):
        if _hit(side, spot, _target_price(target_map, label)):
            return f"{label.upper()}_HIT"

    low, high = _entry_zone(target_map, {})
    if low > 0 and high > 0 and low <= spot <= high:
        return "ACTIVE"
    if side == "CALL" and high > 0 and spot > high:
        return "ACTIVE"
    if side == "PUT" and low > 0 and spot < low:
        return "ACTIVE"

    if str(alert_stage).upper() == "CONFIRMED":
        return "CONFIRMED"
    return "WATCH"


def _catalyst_health(side: str, catalyst: dict[str, Any]) -> dict[str, Any]:
    bias = str(catalyst.get("directional_bias") or "neutral").lower()
    conflict = (side == "CALL" and bias == "bearish") or (
        side == "PUT" and bias == "bullish"
    )
    impact = catalyst.get("explosion_impact")
    impact = impact if isinstance(impact, dict) else {}
    return {
        "verification_state": catalyst.get("verification_state"),
        "cause_status_ar": catalyst.get("cause_status_ar"),
        "directional_bias": bias,
        "conflict_with_contract": conflict,
        "impact_score": impact.get("score"),
        "impact_label": impact.get("label"),
        "impact_label_ar": impact.get("label_ar"),
        "headline": catalyst.get("headline"),
        "source": catalyst.get("primary_source"),
        "url": catalyst.get("primary_url"),
    }


def update_contract_guardian(
    payload: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_quote_age_minutes: float = 120.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Track selected Omega contracts without changing signal authority.

    Guardian state is post-selection observability. It cannot promote WATCH to
    CONFIRMED and cannot bypass V11.
    """
    now = _utc(now)
    state = state if isinstance(state, dict) else {}
    contracts_state = state.get("contracts")
    if not isinstance(contracts_state, dict):
        contracts_state = {}

    current_rows = {
        str(row.get("contract_symbol") or "").replace(" ", "").upper(): row
        for row in _contract_rows(payload)
        if str(row.get("contract_symbol") or "").strip()
    }
    selected = _selected(payload)
    stocks = _stock_map(payload)
    opportunities = _opportunity_map(payload)
    catalysts = _catalyst_map(payload)

    for contract, selected_row in selected.items():
        symbol = selected_row["symbol"]
        primary = dict(selected_row["primary"])
        stock = stocks.get(symbol, {})
        opportunity = opportunities.get(symbol, {})
        catalyst = catalysts.get(symbol, {})
        target_map = _target_map(stock, opportunity)
        if contract not in contracts_state:
            entry_premium, entry_method = _mark(primary, entry=True)
            contracts_state[contract] = {
                "contract_symbol": contract,
                "symbol": symbol,
                "side": str(primary.get("side") or "").upper(),
                "strike": primary.get("strike"),
                "expiration": primary.get("expiration"),
                "created_at": now.isoformat(),
                "entry_premium_reference": round(entry_premium, 6),
                "entry_method": entry_method,
                "entry_iv": _number(primary.get("iv")),
                "entry_underlying": _number(
                    primary.get("underlying_price"),
                    _number(stock.get("price")),
                ),
                "original_alert_stage": primary.get("alert_stage"),
                "original_contract_rank": primary.get("contract_rank"),
                "original_strict_score": primary.get("strict_score"),
                "premium_targets": primary.get("premium_targets") or {},
                "target_map": target_map,
                "target_horizon": opportunity.get("target_horizon") or {},
                "catalyst_at_entry": _catalyst_health(
                    str(primary.get("side") or "").upper(),
                    catalyst,
                ),
                "observations": [],
                "quote_snapshots": [],
                "unstamped_research_observations": [],
                "quote_history_kind": "SELF_COLLECTED_PROVIDER_STAMPED_RESEARCH",
                "mfe_pct": 0.0,
                "mae_pct": 0.0,
                "stage": str(primary.get("alert_stage") or "WATCH").upper(),
                "terminal": False,
            }

    for contract, tracked in list(contracts_state.items()):
        if not isinstance(tracked, dict):
            continue
        if tracked.get("terminal") is True:
            continue
        symbol = str(tracked.get("symbol") or "").upper()
        side = str(tracked.get("side") or "").upper()
        selected_row = selected.get(contract, {})
        primary = (
            selected_row.get("primary")
            if isinstance(selected_row.get("primary"), dict)
            else {}
        )
        current = current_rows.get(contract) or primary
        stock = stocks.get(symbol, {})
        opportunity = opportunities.get(symbol, {})
        catalyst = catalysts.get(symbol, {})
        target_map = (
            tracked.get("target_map")
            if isinstance(tracked.get("target_map"), dict)
            else _target_map(stock, opportunity)
        )

        mark, mark_method = _mark(current, entry=False)
        spot = _number(
            current.get("underlying_price"),
            _number(stock.get("price"), _number(tracked.get("entry_underlying"))),
        )
        entry = _number(tracked.get("entry_premium_reference"))
        return_pct = (
            (mark / entry - 1.0) * 100.0
            if entry > 0 and mark > 0
            else None
        )
        quote_age = _quote_age_minutes(current, now)
        data_stale = quote_age is None or quote_age > max_quote_age_minutes
        current_iv = _number(current.get("iv"))
        entry_iv = _number(tracked.get("entry_iv"))
        iv_change_pct = (
            (current_iv / entry_iv - 1.0) * 100.0
            if current_iv > 0 and entry_iv > 0
            else None
        )
        iv_crush_risk = iv_change_pct is not None and iv_change_pct <= -20.0
        chart = chart_risk_context(stock, side, target_map)
        catalyst_report = catalyst_report_ar(symbol, catalyst, stock, chart)
        quote_snapshots, history_note = record_option_quote_snapshot(
            tracked.get("quote_snapshots"),
            current,
            now=now,
            max_age_minutes=max_quote_age_minutes,
        )
        tracked["quote_snapshots"] = quote_snapshots
        tracked["quote_history_status"] = history_note
        tracked["quote_history_count"] = len(quote_snapshots)
        unstamped, unstamped_note = record_unstamped_research_observation(
            tracked.get("unstamped_research_observations"),
            current,
            now=now,
        )
        tracked["unstamped_research_observations"] = unstamped
        tracked["unstamped_history_status"] = unstamped_note
        tracked["unstamped_research_count"] = len(unstamped)
        tracked["chart_health"] = chart
        tracked["explosion_thesis"] = catalyst_report

        proposed_stage = _state_stage(
            side=side,
            spot=spot,
            target_map=target_map,
            alert_stage=primary.get("alert_stage") or tracked.get("original_alert_stage"),
            expiration=tracked.get("expiration"),
            now=now,
        )

        observation = {
            "at": now.isoformat(),
            "stage": proposed_stage,
            "mark": round(mark, 6) if mark > 0 else None,
            "mark_method": mark_method,
            "return_pct": round(return_pct, 4) if return_pct is not None else None,
            "underlying_price": round(spot, 6) if spot > 0 else None,
            "iv": round(current_iv, 6) if current_iv > 0 else None,
            "iv_change_pct": round(iv_change_pct, 3) if iv_change_pct is not None else None,
            "iv_crush_risk": iv_crush_risk,
            "quote_age_minutes": round(quote_age, 2) if quote_age is not None else None,
            "data_stale": data_stale,
            "source": current.get("source"),
            "freshness_label": current.get("freshness_label"),
        }
        observations = tracked.get("observations")
        if not isinstance(observations, list):
            observations = []
        observations.append(observation)
        tracked["observations"] = observations[-120:]

        # Performance extremes use only valid, provider-stamped fresh
        # research snapshots. Repeated/stale snapshots never raise MFE/MAE.
        returns = [
            (_number(item.get("mark_for_exit")) / entry - 1.0) * 100.0
            for item in quote_snapshots
            if entry > 0 and _number(item.get("mark_for_exit")) > 0
        ]
        if returns:
            tracked["mfe_pct"] = round(max(returns), 4)
            tracked["mae_pct"] = round(min(returns), 4)
        else:
            tracked["mfe_pct"] = None
            tracked["mae_pct"] = None

        previous = str(tracked.get("stage") or "WATCH")
        if previous in TERMINAL_STAGES:
            proposed_stage = previous
        tracked["previous_stage"] = previous
        tracked["stage"] = proposed_stage
        tracked["stage_changed"] = proposed_stage != previous
        tracked["terminal"] = proposed_stage in TERMINAL_STAGES
        tracked["last_observed_at"] = now.isoformat()
        tracked["last_mark"] = observation["mark"]
        tracked["last_return_pct"] = observation["return_pct"]
        tracked["last_underlying_price"] = observation["underlying_price"]
        tracked["quote_age_minutes"] = observation["quote_age_minutes"]
        tracked["data_stale"] = data_stale
        tracked["iv_crush_risk"] = iv_crush_risk
        tracked["catalyst_health"] = _catalyst_health(side, catalyst)

    active = [
        row for row in contracts_state.values()
        if isinstance(row, dict) and row.get("terminal") is not True
    ]
    terminal = [
        row for row in contracts_state.values()
        if isinstance(row, dict) and row.get("terminal") is True
    ]
    active.sort(
        key=lambda row: (
            1 if row.get("stage") == "T2_HIT" else 0,
            1 if row.get("stage") == "T1_HIT" else 0,
            _number(row.get("last_return_pct"), -999.0),
        ),
        reverse=True,
    )

    output = {
        "version": "CONTRACT_GUARDIAN_V1",
        "generated_at": now.isoformat(),
        "decision_authority": False,
        "can_promote_v11": False,
        "tracked_total": len(contracts_state),
        "active_count": len(active),
        "terminal_count": len(terminal),
        "active": active,
        "terminal_recent": terminal[-25:],
        "policy": {
            "entry_reference": "ask when available",
            "observation_reference": "bid when available",
            "targets": "frozen underlying T1/T2/T3 from original thesis",
            "premium_targets": "Black-Scholes scenario ranges are research estimates only",
            "stale_option_quotes_do_not_validate_premium_outcomes": True,
            "snapshot_history": "provider-quote-timestamped self-collected research observations; not historical OPRA",
            "unstamped_history": "collected-at only when quote timestamp is missing; no freshness, return or execution authority",
            "chart_and_catalyst_are_context_only": True,
        },
    }
    state_out = {
        "schema_version": 1,
        "updated_at": now.isoformat(),
        "contracts": contracts_state,
    }
    return output, state_out


def render_guardian_ar(report: dict[str, Any], *, limit: int = 8) -> str:
    rows = report.get("active") if isinstance(report.get("active"), list) else []
    lines = ["BLACK BOX Ω — متابعة العقود المقترحة"]
    if not rows:
        lines.append("لا توجد عقود نشطة في المتابعة حاليًا.")
        return "\n".join(lines)

    for row in rows[: max(1, limit)]:
        side = str(row.get("side") or "")
        symbol = str(row.get("symbol") or "")
        stage = str(row.get("stage") or "")
        ret = row.get("last_return_pct")
        ret_text = f"{_number(ret):+.1f}%" if ret is not None else "—"
        spot = row.get("last_underlying_price")
        premium = row.get("last_mark")
        health = row.get("catalyst_health") if isinstance(row.get("catalyst_health"), dict) else {}
        impact = health.get("impact_score")
        stale = " | بيانات قديمة" if row.get("data_stale") else ""
        iv_risk = " | خطر IV Crush" if row.get("iv_crush_risk") else ""
        lines.append(
            f"{symbol} {side} | {stage} | العقد {premium if premium is not None else '—'} "
            f"({ret_text}) | السهم {spot if spot is not None else '—'}"
            f" | محفز {impact if impact is not None else '—'}/100{stale}{iv_risk}"
        )
    return "\n".join(lines)
