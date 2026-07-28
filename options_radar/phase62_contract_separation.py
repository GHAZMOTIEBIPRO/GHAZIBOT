from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from . import phase62_policy

_OCC_TYPE_RE = re.compile(r"\d{6}([CP])\d{8}$", re.IGNORECASE)
_ORIGINAL_APPLY = phase62_policy.apply_phase62_overlay
_INSTALLED = False


def _contract_key(row: dict[str, Any]) -> str:
    return phase62_policy._text(row.get("contract_symbol")).replace("O:", "").replace(" ", "").upper()


def _type_from_contract_symbol(contract: str) -> str:
    match = _OCC_TYPE_RE.search(contract)
    if not match:
        return ""
    return "call" if match.group(1).upper() == "C" else "put"


def normalize_option_type(row: dict[str, Any]) -> str:
    """Return call/put, treating the OCC contract symbol as authoritative."""
    contract_type = _type_from_contract_symbol(_contract_key(row))
    if contract_type:
        return contract_type

    raw = phase62_policy._text(row.get("option_type")).lower()
    if raw in {"call", "c", "calls"}:
        return "call"
    if raw in {"put", "p", "puts"}:
        return "put"
    return ""


def _stock_direction_map(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in payload.get("stocks", []) or []:
        if not isinstance(row, dict):
            continue
        symbol = phase62_policy._text(row.get("symbol")).upper()
        side = phase62_policy._text(row.get("setup_side") or row.get("side")).lower()
        if side in {"call", "c", "calls"}:
            result[symbol] = "call"
        elif side in {"put", "p", "puts"}:
            result[symbol] = "put"
    return result


def _rank_candidate(raw: dict[str, Any], contract: str, option_type: str) -> dict[str, Any]:
    rejection_codes = phase62_policy._rejection_codes(raw.get("rejection_reason"))
    hard_reject = bool(rejection_codes & phase62_policy._HARD_OPTION_REJECTIONS)
    source = phase62_policy._text(raw.get("source"))
    classes = set(phase62_policy._classes([source], "option"))
    quality, quality_reasons = phase62_policy._option_quality(raw)
    flow_score = phase62_policy._number(raw.get("flow_momentum_score"))

    if not hard_reject and quality and "options_quote" in classes and flow_score >= 55:
        tier = "B"
        decision = "B — فرصة عقد قريبة من الشروط وتحتاج تأكيدًا ثانيًا"
    else:
        tier = "C"
        decision = "C — عقد مرفوض حاليًا مع إظهار سبب الرفض"

    missing: list[str] = []
    if "options_flow" not in classes:
        missing.append("مصدر Flow مستقل")
    if "options_quote" not in classes:
        missing.append("Quote موثوق")
    missing.extend(quality_reasons)
    missing.extend(sorted(rejection_codes))

    volume = phase62_policy._number(raw.get("volume"))
    open_interest = phase62_policy._number(raw.get("open_interest"))
    spread = phase62_policy._number(raw.get("spread_pct"), 1.0)
    liquidity_bonus = min(volume / 1000.0, 20.0) + min(open_interest / 2000.0, 10.0)
    spread_bonus = max(0.0, 10.0 - spread * 50.0)
    rank = flow_score + liquidity_bonus + spread_bonus

    return {
        **raw,
        "contract_symbol": contract,
        "option_type": option_type,
        "opportunity_tier": tier,
        "tier_label": phase62_policy._TIER_LABELS[tier],
        "decision": decision,
        "evidence_classes": sorted(classes),
        "independent_evidence_class_count": len(classes - {"social_attention", "market_context"}),
        "missing_confirmations": list(dict.fromkeys(missing)),
        "research_only": True,
        "_rank": rank,
    }


def _select_diverse_side(
    candidates: list[dict[str, Any]],
    option_type: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    symbol_counts: Counter[str] = Counter()
    symbol_expiry_counts: Counter[tuple[str, str]] = Counter()

    side_rows = [row for row in candidates if row.get("option_type") == option_type]
    side_rows.sort(
        key=lambda row: (
            row.get("opportunity_tier") == "B",
            phase62_policy._number(row.get("_rank")),
        ),
        reverse=True,
    )

    for row in side_rows:
        symbol = phase62_policy._text(row.get("symbol")).upper()
        expiry = phase62_policy._text(row.get("expiration"))[:10]
        if symbol_counts[symbol] >= 2:
            continue
        if symbol_expiry_counts[(symbol, expiry)] >= 1:
            continue
        selected.append(row)
        symbol_counts[symbol] += 1
        symbol_expiry_counts[(symbol, expiry)] += 1
        if len(selected) >= limit:
            break

    return selected


def separated_near_miss_contracts(
    payload: dict[str, Any],
    existing: set[str],
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Build distinct CALL/PUT lists with direction alignment and symbol diversity."""
    direction_by_symbol = _stock_direction_map(payload)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in payload.get("rejected", []) or []:
        if not isinstance(raw, dict) or raw.get("kind") != "option":
            continue
        contract = _contract_key(raw)
        if not contract or contract in existing or contract in seen:
            continue
        option_type = normalize_option_type(raw)
        if option_type not in {"call", "put"}:
            continue

        symbol = phase62_policy._text(raw.get("symbol")).upper()
        expected_side = direction_by_symbol.get(symbol)
        if expected_side and option_type != expected_side:
            continue

        seen.add(contract)
        candidates.append(_rank_candidate(raw, contract, option_type))

    per_side_limit = max(1, limit // 2)
    calls = _select_diverse_side(candidates, "call", per_side_limit)
    puts = _select_diverse_side(candidates, "put", per_side_limit)
    selected = calls + puts

    for row in selected:
        row.pop("_rank", None)
    return selected


def _apply_with_contract_separation(payload: dict[str, Any], settings: Any = None) -> dict[str, Any]:
    result = _ORIGINAL_APPLY(payload, settings)
    watchlist = list(result.get("contract_watchlist", []) or [])
    calls = [row for row in watchlist if normalize_option_type(row) == "call"]
    puts = [row for row in watchlist if normalize_option_type(row) == "put"]
    result["contract_watchlist_calls"] = calls
    result["contract_watchlist_puts"] = puts
    result["contract_watchlist_policy"] = {
        "separate_call_and_put": True,
        "contract_symbol_is_authoritative_for_type": True,
        "match_underlying_setup_direction": True,
        "max_contracts_per_symbol_per_side": 2,
        "max_one_contract_per_symbol_and_expiry": True,
        "call_limit": 12,
        "put_limit": 12,
    }
    summary = result.setdefault("summary", {})
    summary["contract_watchlist_calls"] = len(calls)
    summary["contract_watchlist_puts"] = len(puts)
    return result


def install_contract_separation_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    phase62_policy._near_miss_contracts = separated_near_miss_contracts
    phase62_policy.apply_phase62_overlay = _apply_with_contract_separation
    _INSTALLED = True
