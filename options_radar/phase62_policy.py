from __future__ import annotations

import math
from collections import Counter
from typing import Any

from . import phase61_overlay
from .spx_0dte import build_spx_0dte_status
from .settings import Settings

_TIER_LABELS = {
    "A": "A — مكتمل التأكيد البحثي",
    "B": "B — فرصة قيد التأكيد",
    "C": "C — بيانات غير كافية أو مخاطرة مرتفعة",
}

_CONTEXT_ONLY_SOURCES = {"finra reg sho"}
_SOCIAL_HINTS = ("x recent", "twitter", "reddit", "stocktwits")
_FLOW_HINTS = (
    "benzinga option", "options flow", "cheddar", "unusual whales",
    "trade alert", "livevol", "flowalert", "sweep",
)
_OPTION_QUOTE_HINTS = (
    "polygon_options", "polygon options", "massive opra", "opra",
    "tradier", "marketdata", "alpaca_options", "alpaca options",
    "finnhub", "yahoo", "yfinance",
)
_STOCK_QUOTE_HINTS = (
    "tiingo", "finnhub", "polygon", "massive", "alpaca", "tradier",
    "twelve", "alpha vantage", "yahoo", "yfinance", "iex", "sip",
)
_OFFICIAL_HINTS = (
    "sec", "edgar", "openfda", "fda", "investor relations",
    "company filing", "form 4", "13d", "8-k", "10-q", "10-k",
)
_NEWS_HINTS = ("alpha vantage news", "benzinga news", "news sentiment")
_MARKET_CONTEXT_HINTS = ("finra", "fred", "treasury", "vix", "macro")

_HARD_OPTION_REJECTIONS = {
    "adjusted_or_nonstandard_contract",
    "invalid_bid_ask",
    "data_quality_too_low",
    "last_trade_too_old",
    "spread_above_15pct",
    "spread_too_wide",
    "option_volume_below_200",
    "option_volume_too_low",
    "open_interest_below_100",
    "open_interest_too_low",
    "missing_last_trade",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _merge_unique(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group or []:
            item = _text(value)
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
    return result


def source_class(source: str, domain: str = "generic") -> str:
    text = _text(source).lower()
    if not text:
        return "unknown"
    if any(hint in text for hint in _SOCIAL_HINTS):
        return "social_attention"
    if any(hint in text for hint in _FLOW_HINTS):
        return "options_flow"
    if text in _CONTEXT_ONLY_SOURCES or any(hint in text for hint in _MARKET_CONTEXT_HINTS):
        return "market_context"
    if any(hint in text for hint in _OFFICIAL_HINTS):
        return "official_catalyst"
    if any(hint in text for hint in _NEWS_HINTS):
        return "news_sentiment"
    if domain == "stock" and any(hint in text for hint in _STOCK_QUOTE_HINTS):
        return "stock_quote"
    if domain == "option" and any(hint in text for hint in _OPTION_QUOTE_HINTS):
        return "options_quote"
    if any(hint in text for hint in _OPTION_QUOTE_HINTS):
        return "options_quote"
    if any(hint in text for hint in _STOCK_QUOTE_HINTS):
        return "stock_quote"
    return "other"


def _classes(sources: list[str], domain: str = "generic") -> list[str]:
    values = {source_class(source, domain) for source in sources}
    return sorted(value for value in values if value not in {"unknown", "other"})


def _stock_missing(classes: set[str], strong: bool) -> list[str]:
    missing: list[str] = []
    if "stock_quote" not in classes:
        missing.append("مصدر سعر سوقي موثوق")
    if not ({"official_catalyst", "news_sentiment"} & classes):
        missing.append("محفز أو تأكيد اتجاهي مستقل")
    if not strong:
        missing.append("اكتمال الإعداد الفني ومنطقة الدخول")
    return missing


def _apply_stock_tiers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stocks = {
        _text(row.get("symbol")).upper(): row
        for row in payload.get("stocks", []) or []
        if isinstance(row, dict)
    }
    output: list[dict[str, Any]] = []
    for item in payload.get("stock_recommendations", []) or []:
        if not isinstance(item, dict):
            continue
        symbol = _text(item.get("symbol")).upper()
        stock = stocks.get(symbol, {})
        sources = _merge_unique(
            list(item.get("confirmed_sources") or []),
            list(item.get("directional_confirmation_sources") or []),
            list(item.get("official_sources") or []),
            list(item.get("supporting_context_sources") or []),
            list(item.get("social_sources") or []),
        )
        classes = set(_classes(sources, "stock"))
        score = _number(stock.get("score") or item.get("score"))
        entry_state = _text(stock.get("entry_state")).lower()
        strong = bool(stock.get("new_stock_setup")) and score >= 74 and entry_state in {"early", "confirmed"}
        independent_directional = bool({"official_catalyst", "news_sentiment"} & classes)
        market_confirmed = "stock_quote" in classes
        if strong and market_confirmed and independent_directional:
            tier = "A"
            decision = "A — مرشح بحثي مشروط بعد تحقق منطقة الدخول"
        elif score >= 68 and market_confirmed:
            tier = "B"
            decision = "B — فرصة قيد التأكيد قبل اعتمادها"
        else:
            tier = "C"
            decision = "C — مراقبة فقط؛ البيانات أو التأكيد غير مكتمل"
        missing = _stock_missing(classes, strong)
        item.update(
            {
                "opportunity_tier": tier,
                "tier_label": _TIER_LABELS[tier],
                "decision": decision,
                "evidence_classes": sorted(classes),
                "independent_evidence_class_count": len(classes - {"social_attention", "market_context"}),
                "missing_confirmations": missing,
                "research_only": True,
                "automatic_execution": False,
            }
        )
        stock["opportunity_tier"] = tier
        stock["tier_label"] = _TIER_LABELS[tier]
        stock["missing_confirmations"] = missing
        output.append(item)
    return output


def _rejection_codes(value: Any) -> set[str]:
    return {item.strip() for item in _text(value).split(",") if item.strip()}


def _option_quality(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    bid = _number(row.get("bid"), -1.0)
    ask = _number(row.get("ask"), -1.0)
    spread = _number(row.get("spread_pct"), -1.0)
    if spread < 0 and bid >= 0 and ask > 0:
        spread = max(0.0, (ask - bid) / ask)
    volume = _number(row.get("volume"))
    open_interest = _number(row.get("open_interest"))
    age = _number(row.get("last_trade_age_minutes"), 9999.0)
    if bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("Bid/Ask غير صالح")
    if spread < 0 or spread > 0.15:
        reasons.append("السبريد أعلى من 15%")
    if volume < 200:
        reasons.append("حجم العقد أقل من 200")
    if open_interest < 100:
        reasons.append("Open Interest أقل من 100")
    if age > 30:
        reasons.append("آخر صفقة قديمة")
    return not reasons, reasons


def _option_sources(item: dict[str, Any], row: dict[str, Any]) -> list[str]:
    external = item.get("external_evidence") or {}
    return _merge_unique(
        list(item.get("confirmed_sources") or []),
        list(external.get("market_flow_sources") or []),
        [_text(row.get("source"))] if row.get("source") else [],
    )


def _tier_contract(item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    sources = _option_sources(item, row)
    classes = set(_classes(sources, "option"))
    quality, quality_reasons = _option_quality(row)
    flow_score = _number(row.get("flow_momentum_score") or item.get("flow_score"))
    unusual = bool(row.get("unusual_activity_flag"))
    aggressive = _text(row.get("buying_flow_type")) == "Aggressive Buying"
    has_quote = "options_quote" in classes
    has_flow = "options_flow" in classes
    if quality and has_quote and has_flow and unusual and aggressive and flow_score >= 72:
        tier = "A"
        decision = "A — عقد مكتمل التأكيد البحثي بعد تحقق السعر"
    elif quality and has_quote and flow_score >= 55:
        tier = "B"
        decision = "B — عقد قيد التأكيد؛ ينتظر Flow مستقل"
    else:
        tier = "C"
        decision = "C — عقد غير مكتمل أو مخاطره التنفيذية مرتفعة"
    missing: list[str] = []
    if not has_quote:
        missing.append("Quote موثوق للعقد")
    if not has_flow:
        missing.append("مصدر Flow مستقل")
    missing.extend(quality_reasons)
    item.update(
        {
            "opportunity_tier": tier,
            "tier_label": _TIER_LABELS[tier],
            "decision": decision,
            "evidence_classes": sorted(classes),
            "independent_evidence_class_count": len(classes - {"social_attention", "market_context"}),
            "missing_confirmations": list(dict.fromkeys(missing)),
            "research_only": True,
            "automatic_execution": False,
        }
    )
    row["opportunity_tier"] = tier
    row["tier_label"] = _TIER_LABELS[tier]
    row["missing_confirmations"] = item["missing_confirmations"]
    return item


def _apply_contract_tiers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(payload.get("top_calls", []) or []) + list(payload.get("top_puts", []) or []) + list(payload.get("options", []) or [])
    contract_map = {
        _text(row.get("contract_symbol")).replace("O:", "").replace(" ", ""): row
        for row in rows
        if isinstance(row, dict) and row.get("contract_symbol")
    }
    output: list[dict[str, Any]] = []
    for item in payload.get("contract_recommendations", []) or []:
        if not isinstance(item, dict):
            continue
        key = _text(item.get("contract_symbol")).replace("O:", "").replace(" ", "")
        row = contract_map.get(key, {})
        output.append(_tier_contract(item, row))
    return output


def _near_miss_contracts(payload: dict[str, Any], existing: set[str], limit: int = 24) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in payload.get("rejected", []) or []:
        if not isinstance(raw, dict) or raw.get("kind") != "option":
            continue
        contract = _text(raw.get("contract_symbol")).replace("O:", "").replace(" ", "")
        if not contract or contract in existing:
            continue
        rejection_codes = _rejection_codes(raw.get("rejection_reason"))
        hard_reject = bool(rejection_codes & _HARD_OPTION_REJECTIONS)
        source = _text(raw.get("source"))
        classes = set(_classes([source], "option"))
        quality, quality_reasons = _option_quality(raw)
        flow_score = _number(raw.get("flow_momentum_score"))
        if not hard_reject and quality and "options_quote" in classes and flow_score >= 55:
            tier = "B"
            status = "B — فرصة عقد قريبة من الشروط وتحتاج تأكيدًا ثانيًا"
        else:
            tier = "C"
            status = "C — عقد مرفوض حاليًا مع إظهار سبب الرفض"
        missing = []
        if "options_flow" not in classes:
            missing.append("مصدر Flow مستقل")
        if "options_quote" not in classes:
            missing.append("Quote موثوق")
        missing.extend(quality_reasons)
        if rejection_codes:
            missing.extend(sorted(rejection_codes))
        score = flow_score + min(_number(raw.get("volume")) / 1000.0, 20.0) + min(_number(raw.get("open_interest")) / 2000.0, 10.0)
        candidates.append(
            {
                **raw,
                "contract_symbol": contract,
                "opportunity_tier": tier,
                "tier_label": _TIER_LABELS[tier],
                "decision": status,
                "evidence_classes": sorted(classes),
                "independent_evidence_class_count": len(classes - {"social_attention", "market_context"}),
                "missing_confirmations": list(dict.fromkeys(missing)),
                "research_only": True,
                "_rank": score,
            }
        )
    candidates.sort(key=lambda row: (row.get("opportunity_tier") == "B", _number(row.get("_rank"))), reverse=True)
    for row in candidates:
        row.pop("_rank", None)
    return candidates[:limit]


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(_text(item.get("opportunity_tier")) for item in items)
    return {tier: int(counts.get(tier, 0)) for tier in ("A", "B", "C")}


def apply_phase62_overlay(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    payload = phase61_overlay.apply_phase61_overlay(payload, settings)
    stock_items = _apply_stock_tiers(payload)
    contract_items = _apply_contract_tiers(payload)
    existing_contracts = {
        _text(item.get("contract_symbol")).replace("O:", "").replace(" ", "")
        for item in contract_items
        if item.get("contract_symbol")
    }
    watchlist = _near_miss_contracts(payload, existing_contracts)
    payload["contract_watchlist"] = watchlist
    payload["spx_0dte"] = build_spx_0dte_status(payload)
    payload["schema_version"] = 6
    payload["phase"] = "6.2"
    payload["model_version"] = "2026.07-phase6.2-evidence-tiers"
    stock_counts = _counts(stock_items)
    contract_counts = _counts(contract_items + watchlist)
    payload["opportunity_tiers"] = {
        "policy": {
            "A": "إعداد فني + Quote موثوق + فئة دليل مستقلة ثانية؛ للعقد يلزم Quote وFlow مستقل.",
            "B": "الإعداد قريب من الاكتمال لكنه ينتظر تأكيدًا أو مصدرًا مستقلًا.",
            "C": "بيانات ناقصة أو سيولة/سبريد/حداثة غير مناسبة.",
            "provider_names_are_not_counted_as_independent_when_they_share_the_same_evidence_class": True,
            "social_and_finra_are_supporting_context_only": True,
            "research_only": True,
            "automatic_execution": False,
        },
        "stocks": stock_counts,
        "contracts": contract_counts,
    }
    summary = payload.setdefault("summary", {})
    summary.update(
        {
            "stock_tier_a": stock_counts["A"],
            "stock_tier_b": stock_counts["B"],
            "stock_tier_c": stock_counts["C"],
            "contract_tier_a": contract_counts["A"],
            "contract_tier_b": contract_counts["B"],
            "contract_tier_c": contract_counts["C"],
            "contract_watchlist": len(watchlist),
            "stock_recommendations": stock_counts["A"],
            "contract_recommendations": contract_counts["A"],
        }
    )
    payload.setdefault("recommendation_policy", {}).update(
        {
            "evidence_class_independence_required": True,
            "tiers": ["A", "B", "C"],
            "tier_a_is_research_candidate_not_order": True,
            "near_miss_contracts_are_published_as_watchlist": True,
            "spx_0dte_is_separate_from_swing": True,
        }
    )
    payload["disclaimer"] = (
        "Phase 6.2 يفصل الأسهم والعقود وSPX 0DTE. درجة A تعني اكتمال شروط البحث فقط "
        "ولا تعني أمر شراء. درجة B تنتظر تأكيدًا إضافيًا، وC بياناتها أو مخاطر تنفيذها غير مناسبة. "
        "X وReddit وFINRA سياق مساند فقط، ولا يوجد تنفيذ آلي أو ضمان ربح."
    )
    return payload
