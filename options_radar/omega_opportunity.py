from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from .omega_target_map import build_target_maps


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _freshness_ok(option: dict[str, Any]) -> bool:
    status = str(option.get("data_status") or "").lower()
    freshness = str(option.get("freshness_label") or "").lower()
    age = _number(option.get("last_trade_age_minutes"), 10_000)
    if any(token in status for token in ("stale", "missing", "invalid")):
        return False
    if "stale" in freshness:
        return False
    return age <= 30 or age == 10_000


def _tradable_contract(option: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    bid = _number(option.get("bid"))
    ask = _number(option.get("ask"))
    spread = _number(option.get("spread_pct"), 9.0)
    volume = _number(option.get("volume"))
    oi = _number(option.get("open_interest"))
    if bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("invalid_bid_ask")
    if spread > 0.25:
        reasons.append("spread_too_wide")
    if volume < 10 and oi < 25:
        reasons.append("thin_contract")
    if not _freshness_ok(option):
        reasons.append("stale_option_data")
    if str(option.get("liquidity_grade") or "").upper() in {"D", "F", "X"}:
        reasons.append("liquidity_grade_reject")
    return not reasons, reasons


def _best_option_by_symbol(options: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for option in options:
        if not isinstance(option, dict):
            continue
        symbol = str(option.get("symbol") or "").upper()
        side = str(option.get("option_type") or "").lower()
        if symbol and side in {"call", "put"}:
            grouped[(symbol, side)].append(option)

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in grouped.items():
        rows.sort(
            key=lambda row: (
                1 if _tradable_contract(row)[0] else 0,
                _number(row.get("contract_score"), _number(row.get("score"))),
                _number(row.get("flow_momentum_score")),
                -_number(row.get("spread_pct"), 9.0),
            ),
            reverse=True,
        )
        result[key] = rows[0]
    return result


def _catalyst_dimension(cluster: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not cluster:
        return 20.0, ["No validated high-impact catalyst cluster"]
    score = _number(cluster.get("catalyst_quality"))
    reasons = [
        f"Catalyst quality {score:.0f}/100",
        f"Reaction {cluster.get('reaction_state', 'UNKNOWN')}",
    ]
    return score, reasons


def _participation_dimension(stock: dict[str, Any]) -> tuple[float, list[str]]:
    rvol = max(
        _number(stock.get("finviz_relative_volume")),
        _number(stock.get("relative_volume")),
    )
    dollar_volume = _number(stock.get("avg_dollar_volume"))
    gap = abs(_number(stock.get("gap_pct")))
    score = 25.0
    score += min(45.0, max(0.0, (rvol - 0.8) * 28.0))
    if dollar_volume >= 100_000_000:
        score += 22
    elif dollar_volume >= 30_000_000:
        score += 16
    elif dollar_volume >= 10_000_000:
        score += 10
    elif dollar_volume >= 3_000_000:
        score += 4
    score += min(10.0, gap * 1.5)
    reasons = [f"RVOL {rvol:.2f}", f"20D avg dollar volume {dollar_volume:,.0f}"]
    if gap:
        reasons.append(f"Gap {gap:.1f}%")
    return _bounded(score), reasons


def _supply_dimension(stock: dict[str, Any]) -> tuple[float, list[str], bool]:
    float_shares = _number(stock.get("float_shares"), _number(stock.get("float")))
    short_float = _number(stock.get("short_float"), _number(stock.get("short_float_pct")))
    dollar_volume = _number(stock.get("avg_dollar_volume"))
    unknown = float_shares <= 0 and short_float <= 0
    score = 50.0 if unknown else 55.0
    reasons: list[str] = []
    if float_shares > 0:
        if float_shares <= 20_000_000:
            score += 18
        elif float_shares <= 75_000_000:
            score += 10
        elif float_shares > 500_000_000:
            score -= 8
        reasons.append(f"Float {float_shares:,.0f}")
    else:
        reasons.append("Float unavailable")
    if short_float > 0:
        normalized_short = short_float * 100 if short_float <= 1 else short_float
        score += min(22.0, normalized_short * 0.9)
        reasons.append(f"Short float {normalized_short:.1f}%")
    if float_shares and float_shares <= 20_000_000 and dollar_volume < 3_000_000:
        reasons.append("Low float without execution liquidity")
        return 0.0, reasons, True
    return _bounded(score), reasons, False


def _price_dimension(stock: dict[str, Any]) -> tuple[float, list[str], float]:
    score = _number(stock.get("score"), 45.0) * 0.58
    score += min(22.0, abs(_number(stock.get("relative_strength_20d"))) * 500)
    if bool(stock.get("breakout")):
        score += 16
    state = str(stock.get("entry_state") or "")
    if state == "confirmed":
        score += 12
    elif state == "early":
        score += 7
    elif state == "too_late":
        score -= 25
    distance = abs(_number(stock.get("distance_to_trigger_atr")))
    chase = max(0.0, (distance - 1.2) * 20)
    score -= chase
    return _bounded(score), [f"Setup {state or 'unknown'}", f"Trigger distance {distance:.2f} ATR"], _bounded(chase)


def _options_dimension(option: dict[str, Any] | None) -> tuple[float, list[str], bool]:
    if not option:
        return 0.0, ["No option candidate"], False
    tradable, rejection = _tradable_contract(option)
    score = _number(option.get("contract_score"), _number(option.get("score"), 35.0))
    score = score * 0.55 + _number(option.get("flow_momentum_score"), 0.0) * 0.30
    score += min(15.0, _number(option.get("vol_to_oi_ratio")) * 4.0)
    if not tradable:
        score = min(score, 35.0)
    reasons = [
        f"Contract score {_number(option.get('contract_score'), _number(option.get('score'))):.0f}",
        f"Spread {_number(option.get('spread_pct')) * 100:.1f}%",
    ]
    reasons.extend(rejection)
    return _bounded(score), reasons, tradable


def _risk_penalty(
    stock: dict[str, Any],
    cluster: dict[str, Any] | None,
    option: dict[str, Any] | None,
    chase_penalty: float,
) -> tuple[float, list[str]]:
    penalty = chase_penalty
    reasons: list[str] = []
    if cluster:
        dilution = _number(cluster.get("dilution_risk"))
        penalty += dilution * 0.35
        if dilution >= 60:
            reasons.append(f"Dilution risk {dilution:.0f}/100")
        if str(cluster.get("reaction_state")) == "EXTENDED_CHASING_RISK":
            penalty += 15
            reasons.append("Catalyst chase risk")
    if str(stock.get("rejection_reason") or ""):
        penalty += 30
        reasons.append(str(stock.get("rejection_reason")))
    if option:
        tradable, option_reasons = _tradable_contract(option)
        if not tradable:
            penalty += 20
            reasons.extend(option_reasons)
    return min(100.0, penalty), list(dict.fromkeys(reasons))


def _tier(
    ranking: float,
    available_dimensions: int,
    *,
    fresh: bool,
    valid_setup: bool,
    tradable_contract: bool,
    critical_risk: bool,
) -> str:
    if critical_risk or not valid_setup:
        return "X"
    if not fresh or not tradable_contract:
        return "B" if ranking >= 65 else "C"
    if ranking >= 90 and available_dimensions >= 5:
        return "A+"
    if ranking >= 80 and available_dimensions >= 4:
        return "A"
    if ranking >= 65:
        return "B"
    return "C"


def _day_decision(stock: dict[str, Any], participation: float, price_structure: float, catalyst: float, risk: float) -> str:
    side = str(stock.get("setup_side") or "").lower()
    score = participation * 0.42 + price_structure * 0.33 + catalyst * 0.25 - risk * 0.35
    rvol = max(_number(stock.get("finviz_relative_volume")), _number(stock.get("relative_volume")))
    if score < 58 or rvol < 1.1 or side not in {"call", "put"}:
        return "NO TRADE"
    return "DAY CALL" if side == "call" else "DAY PUT"


def _swing_decision(stock: dict[str, Any], catalyst: float, price_structure: float, risk: float) -> str:
    side = str(stock.get("setup_side") or "").lower()
    score = _number(stock.get("score")) * 0.45 + catalyst * 0.25 + price_structure * 0.30 - risk * 0.30
    if str(stock.get("rejection_reason") or "") or score < 45:
        return "REJECT"
    if score < 62 or side not in {"call", "put"}:
        return "WATCH"
    return "SWING CALL" if side == "call" else "SWING PUT"


def build_omega_opportunities(
    payload: dict[str, Any],
    catalyst_intelligence: dict[str, Any],
) -> dict[str, Any]:
    stocks = [row for row in payload.get("stocks", []) if isinstance(row, dict)]
    options = [
        row for row in (payload.get("top_calls", []) + payload.get("top_puts", []) + payload.get("options", []))
        if isinstance(row, dict)
    ]
    option_map = _best_option_by_symbol(options)
    catalyst_map = catalyst_intelligence.get("by_symbol", {}) if isinstance(catalyst_intelligence, dict) else {}
    target_maps = build_target_maps(stocks)

    rows: list[dict[str, Any]] = []
    day: list[dict[str, Any]] = []
    swing: list[dict[str, Any]] = []
    upside: list[dict[str, Any]] = []
    downside: list[dict[str, Any]] = []

    for stock in stocks:
        symbol = str(stock.get("symbol") or "").upper()
        side = str(stock.get("setup_side") or "").lower()
        cluster = catalyst_map.get(symbol)
        option = option_map.get((symbol, side))
        catalyst_score, catalyst_reasons = _catalyst_dimension(cluster)
        participation, participation_reasons = _participation_dimension(stock)
        supply, supply_reasons, low_float_reject = _supply_dimension(stock)
        price_structure, price_reasons, chase = _price_dimension(stock)
        options_score, options_reasons, tradable = _options_dimension(option)
        risk_penalty, risk_reasons = _risk_penalty(stock, cluster, option, chase)

        dimensions = {
            "catalyst": round(catalyst_score, 1),
            "participation": round(participation, 1),
            "supply_structure": round(supply, 1),
            "price_structure": round(price_structure, 1),
            "options_structure": round(options_score, 1),
            "risk_penalty": round(risk_penalty, 1),
        }
        available = sum(
            [
                bool(cluster),
                participation > 0,
                supply > 0,
                price_structure > 0,
                bool(option),
            ]
        )
        base_rank = (
            catalyst_score * 0.24
            + participation * 0.21
            + supply * 0.14
            + price_structure * 0.25
            + options_score * 0.16
        )
        ranking = _bounded(base_rank - risk_penalty * 0.42)
        fresh = bool(not cluster or _number(cluster.get("age_days"), 0) <= 7)
        valid_setup = str(stock.get("setup_status") or "") not in {"too_late"} and not str(stock.get("rejection_reason") or "")
        critical_risk = low_float_reject or _number(cluster.get("dilution_risk") if cluster else 0) >= 85
        tier = _tier(
            ranking,
            available,
            fresh=fresh,
            valid_setup=valid_setup,
            tradable_contract=tradable,
            critical_risk=critical_risk,
        )
        day_decision = _day_decision(stock, participation, price_structure, catalyst_score, risk_penalty)
        swing_decision = _swing_decision(stock, catalyst_score, price_structure, risk_penalty)

        no_contract_state = None
        if valid_setup and _number(stock.get("score")) >= 75 and not tradable:
            no_contract_state = "GREAT STOCK — NO GOOD OPTION"
        if cluster and cluster.get("reaction_state") == "EXTENDED_CHASING_RISK":
            no_contract_state = "STRONG CATALYST — PRICE TOO EXTENDED"
        if critical_risk and cluster and _number(cluster.get("dilution_risk")) >= 85:
            no_contract_state = "DILUTION RISK"

        row = {
            "symbol": symbol,
            "price": stock.get("price"),
            "direction": "UPSIDE" if side == "call" else "DOWNSIDE" if side == "put" else "NEUTRAL",
            "opportunity_tier": tier,
            "explosion_rank": round(ranking, 1),
            "ranking_score_label": "RANKING SCORE — NOT PROBABILITY",
            "dimensions": dimensions,
            "day_decision": day_decision,
            "swing_decision": swing_decision,
            "catalyst": cluster,
            "target_map": target_maps.get(symbol),
            "best_expiry_family": option.get("expiry_family") if option else None,
            "best_contract": option,
            "contract_score": (
                option.get("contract_score", option.get("score")) if option else None
            ),
            "tradable_contract": tradable,
            "why": list(dict.fromkeys(catalyst_reasons + participation_reasons + price_reasons + options_reasons))[:12],
            "risks": list(dict.fromkeys(supply_reasons + risk_reasons))[:12],
            "no_trade_state": no_contract_state,
            "data_fresh": fresh,
            "available_dimensions": available,
            "probability_of_profit": None,
        }
        rows.append(row)
        if day_decision != "NO TRADE":
            day.append(row)
        if swing_decision in {"SWING CALL", "SWING PUT", "WATCH"}:
            swing.append(row)
        if row["direction"] == "UPSIDE":
            upside.append(row)
        elif row["direction"] == "DOWNSIDE":
            downside.append(row)

    sort_key = lambda row: _number(row.get("explosion_rank"))
    for collection in (rows, day, swing, upside, downside):
        collection.sort(key=sort_key, reverse=True)

    return {
        "research_status": "RANKING_ONLY",
        "probability_calibrated": False,
        "omega_day": day,
        "omega_swing": swing,
        "explosion_radar": {
            "upside": upside,
            "downside": downside,
            "dimensions": [
                "Catalyst",
                "Participation",
                "Supply Structure",
                "Price Structure",
                "Options Structure",
                "Risk Penalty",
            ],
        },
        "all_ranked": rows,
        "target_maps": target_maps,
        "summary": {
            "ranked": len(rows),
            "day_opportunities": len(day),
            "swing_opportunities": len(swing),
            "upside_candidates": len(upside),
            "downside_candidates": len(downside),
            "tier_a_plus": sum(row["opportunity_tier"] == "A+" for row in rows),
            "tier_a": sum(row["opportunity_tier"] == "A" for row in rows),
            "tier_b": sum(row["opportunity_tier"] == "B" for row in rows),
            "rejected": sum(row["opportunity_tier"] == "X" for row in rows),
            "no_good_option": sum(bool(row["no_trade_state"]) for row in rows),
        },
    }
