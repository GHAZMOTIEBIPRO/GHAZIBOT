from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path("data/live/spx_0dte_snapshot.json")

_REQUIRED_FIELDS = (
    "spot",
    "orb_high",
    "orb_low",
    "vwap",
    "ema9",
    "ema21",
    "vix",
    "expected_move",
)


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _read_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_status(payload: dict[str, Any]) -> tuple[bool, bool]:
    network = payload.get("source_network") or {}
    stocks = network.get("stocks") or []
    options = network.get("options") or []
    stock_live = any(
        isinstance(item, dict)
        and item.get("used_successfully")
        and str(item.get("category") or "") in {"stocks", "market_data"}
        and "yahoo" not in str(item.get("name") or "").lower()
        for item in stocks
    )
    option_live = any(
        isinstance(item, dict)
        and item.get("used_successfully")
        and str(item.get("category") or "") in {"options", "options_flow"}
        and "yahoo" not in str(item.get("name") or "").lower()
        for item in options
    )
    return stock_live, option_live


def evaluate_spx_0dte_snapshot(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    missing = [field for field in _REQUIRED_FIELDS if _number(snapshot.get(field)) is None]
    source_classes = {
        str(value).strip()
        for value in snapshot.get("source_classes", []) or []
        if str(value).strip()
    }
    if "underlying_intraday" not in source_classes:
        missing.append("underlying_intraday source")
    if missing:
        return {
            "engine": "SPX-0DTE-ORB-v1",
            "status": "waiting_for_snapshot_fields",
            "opportunity_tier": "C",
            "signal": None,
            "missing_requirements": list(dict.fromkeys(missing)),
            "research_only": True,
            "automatic_execution": False,
        }

    spot = _number(snapshot.get("spot"), 0.0) or 0.0
    orb_high = _number(snapshot.get("orb_high"), 0.0) or 0.0
    orb_low = _number(snapshot.get("orb_low"), 0.0) or 0.0
    vwap = _number(snapshot.get("vwap"), 0.0) or 0.0
    ema9 = _number(snapshot.get("ema9"), 0.0) or 0.0
    ema21 = _number(snapshot.get("ema21"), 0.0) or 0.0
    expected_move = abs(_number(snapshot.get("expected_move"), 0.0) or 0.0)
    updated_at = _parse_time(snapshot.get("updated_at"))
    age_minutes = (
        max(0.0, (now - updated_at).total_seconds() / 60.0)
        if updated_at is not None
        else 9999.0
    )

    call_setup = spot > orb_high and spot > vwap and ema9 > ema21
    put_setup = spot < orb_low and spot < vwap and ema9 < ema21
    if call_setup:
        signal = "CALL"
        invalidation = max(orb_high, vwap)
        target_1 = spot + expected_move * 0.25
        target_2 = spot + expected_move * 0.50
    elif put_setup:
        signal = "PUT"
        invalidation = min(orb_low, vwap)
        target_1 = spot - expected_move * 0.25
        target_2 = spot - expected_move * 0.50
    else:
        return {
            "engine": "SPX-0DTE-ORB-v1",
            "status": "no_confirmed_breakout",
            "opportunity_tier": "C",
            "signal": None,
            "spot": spot,
            "orb_high": orb_high,
            "orb_low": orb_low,
            "vwap": vwap,
            "ema9": ema9,
            "ema21": ema21,
            "updated_at": snapshot.get("updated_at"),
            "age_minutes": round(age_minutes, 2),
            "missing_requirements": ["كسر ORB متوافق مع VWAP وEMA 9/21"],
            "research_only": True,
            "automatic_execution": False,
        }

    contract = snapshot.get("candidate_contract") or {}
    bid = _number(contract.get("bid"), -1.0)
    ask = _number(contract.get("ask"), -1.0)
    bid = -1.0 if bid is None else bid
    ask = -1.0 if ask is None else ask
    spread_pct = _number(contract.get("spread_pct"))
    if spread_pct is None and ask > 0 and bid >= 0:
        spread_pct = max(0.0, (ask - bid) / ask)
    quote_valid = bid > 0 and ask > 0 and ask >= bid and spread_pct is not None

    has_quote = "options_quote" in source_classes
    has_flow = "options_flow" in source_classes
    fresh_2m = age_minutes <= 2
    fresh_5m = age_minutes <= 5
    tier_a_spread = spread_pct is not None and spread_pct <= 0.08
    tier_b_spread = spread_pct is not None and spread_pct <= 0.12
    if quote_valid and has_quote and has_flow and fresh_2m and tier_a_spread:
        tier = "A"
        status = "confirmed_research_setup"
    elif quote_valid and has_quote and fresh_5m and tier_b_spread:
        tier = "B"
        status = "watch_pending_flow_confirmation"
    else:
        tier = "C"
        status = "insufficient_execution_quality"

    missing_requirements: list[str] = []
    if not has_quote:
        missing_requirements.append("مصدر Quote لحظي للعقد")
    if not has_flow:
        missing_requirements.append("مصدر Flow مستقل")
    if not quote_valid:
        missing_requirements.append("Bid/Ask صالح")
    if age_minutes > 5:
        missing_requirements.append("بيانات أحدث من 5 دقائق")
    if spread_pct is None or spread_pct > 0.12:
        missing_requirements.append("سبريد 12% أو أقل")

    return {
        "engine": "SPX-0DTE-ORB-v1",
        "status": status,
        "opportunity_tier": tier,
        "signal": signal,
        "spot": round(spot, 4),
        "orb_high": round(orb_high, 4),
        "orb_low": round(orb_low, 4),
        "vwap": round(vwap, 4),
        "ema9": round(ema9, 4),
        "ema21": round(ema21, 4),
        "vix": _number(snapshot.get("vix")),
        "expected_move": expected_move,
        "underlying_invalidation": round(invalidation, 4),
        "underlying_target_1": round(target_1, 4),
        "underlying_target_2": round(target_2, 4),
        "candidate_contract": contract,
        "source_classes": sorted(source_classes),
        "updated_at": snapshot.get("updated_at"),
        "age_minutes": round(age_minutes, 2),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "missing_requirements": missing_requirements,
        "research_only": True,
        "automatic_execution": False,
        "note": "هذا المحرك مستقل عن رادار Swing. GitHub Actions ليس بثًا لحظيًا؛ يلزم Feed حي لتشغيله أثناء الجلسة.",
    }


def build_spx_0dte_status(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = _read_snapshot()
    if snapshot:
        return evaluate_spx_0dte_snapshot(snapshot)

    market_clock = payload.get("market_clock") or {}
    stock_live, option_live = _source_status(payload)
    missing: list[str] = []
    if not stock_live:
        missing.append("مصدر Intraday لحظي لـSPX/SPY")
    if not option_live:
        missing.append("مصدر OPRA/Options Quote لحظي")
    missing.extend(
        [
            "شموع 1m/5m/15m",
            "ORB أول 15 دقيقة",
            "VWAP وEMA 9/21",
            "VIX وExpected Move",
        ]
    )
    return {
        "engine": "SPX-0DTE-ORB-v1",
        "status": "market_closed" if market_clock.get("is_regular_open") is False else "waiting_for_realtime_feed",
        "opportunity_tier": "C",
        "signal": None,
        "market_is_open": bool(market_clock.get("is_regular_open")),
        "live_stock_source_available": stock_live,
        "live_option_source_available": option_live,
        "missing_requirements": list(dict.fromkeys(missing)),
        "snapshot_path": str(SNAPSHOT_PATH),
        "research_only": True,
        "automatic_execution": False,
        "note": "تم بناء محرك 0DTE مستقل، لكنه لا يصدر إشارة من بيانات يومية أو Yahoo. يلزم Feed لحظي قبل التفعيل.",
    }
