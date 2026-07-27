from __future__ import annotations

from typing import Any

from . import phase62_policy

_FALLBACK_NAMES = ("yahoo", "yfinance")
_ORIGINAL_STOCK_TIERS = phase62_policy._apply_stock_tiers
_ORIGINAL_TIER_CONTRACT = phase62_policy._tier_contract
_ORIGINAL_APPLY = phase62_policy.apply_phase62_overlay
_INSTALLED = False


def _sources_from_stock_item(item: dict[str, Any]) -> list[str]:
    return phase62_policy._merge_unique(
        list(item.get("confirmed_sources") or []),
        list(item.get("directional_confirmation_sources") or []),
        list(item.get("official_sources") or []),
        list(item.get("supporting_context_sources") or []),
        list(item.get("social_sources") or []),
    )


def _is_fallback(source: str) -> bool:
    text = str(source or "").strip().lower()
    return any(name in text for name in _FALLBACK_NAMES)


def _has_non_fallback_quote(sources: list[str], domain: str) -> bool:
    expected = "stock_quote" if domain == "stock" else "options_quote"
    return any(
        phase62_policy.source_class(source, domain) == expected
        and not _is_fallback(source)
        for source in sources
    )


def _downgrade_stock_a_without_primary_quote(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = _ORIGINAL_STOCK_TIERS(payload)
    stocks = {
        str(stock.get("symbol") or "").upper(): stock
        for stock in payload.get("stocks", []) or []
        if isinstance(stock, dict)
    }
    for item in rows:
        sources = _sources_from_stock_item(item)
        has_primary_quote = _has_non_fallback_quote(sources, "stock")
        item["primary_market_quote_confirmed"] = has_primary_quote
        item["market_quote_quality"] = "primary_or_licensed" if has_primary_quote else "fallback_only"
        missing = list(item.get("missing_confirmations") or [])
        if not has_primary_quote:
            missing.append("مصدر سوقي مستقل غير Yahoo/YFinance")
        item["missing_confirmations"] = list(dict.fromkeys(missing))
        if item.get("opportunity_tier") == "A" and not has_primary_quote:
            item["opportunity_tier"] = "B"
            item["tier_label"] = phase62_policy._TIER_LABELS["B"]
            item["decision"] = "B — الإعداد قوي لكنه ينتظر سعراً سوقياً مستقلاً غير Yahoo"
        symbol = str(item.get("symbol") or "").upper()
        if symbol in stocks:
            stocks[symbol]["opportunity_tier"] = item.get("opportunity_tier")
            stocks[symbol]["tier_label"] = item.get("tier_label")
            stocks[symbol]["missing_confirmations"] = item["missing_confirmations"]
            stocks[symbol]["market_quote_quality"] = item["market_quote_quality"]
    return rows


def _tier_contract_with_primary_quote(
    item: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    result = _ORIGINAL_TIER_CONTRACT(item, row)
    sources = phase62_policy._option_sources(result, row)
    has_primary_quote = _has_non_fallback_quote(sources, "option")
    result["primary_option_quote_confirmed"] = has_primary_quote
    result["market_quote_quality"] = "primary_or_licensed" if has_primary_quote else "fallback_only"
    missing = list(result.get("missing_confirmations") or [])
    if not has_primary_quote:
        missing.append("Quote مستقل غير Yahoo/YFinance")
    result["missing_confirmations"] = list(dict.fromkeys(missing))
    if result.get("opportunity_tier") == "A" and not has_primary_quote:
        result["opportunity_tier"] = "B"
        result["tier_label"] = phase62_policy._TIER_LABELS["B"]
        result["decision"] = "B — العقد ينتظر Quote مستقلاً غير Yahoo قبل درجة A"
    row["opportunity_tier"] = result.get("opportunity_tier")
    row["tier_label"] = result.get("tier_label")
    row["missing_confirmations"] = result["missing_confirmations"]
    row["market_quote_quality"] = result["market_quote_quality"]
    return result


def _apply_with_quality_policy(
    payload: dict[str, Any],
    settings: Any = None,
) -> dict[str, Any]:
    result = _ORIGINAL_APPLY(payload, settings)
    result.setdefault("recommendation_policy", {}).update(
        {
            "tier_a_requires_non_yahoo_market_quote": True,
            "yahoo_and_yfinance_are_fallback_only": True,
            "fallback_quote_can_reach_tier_b_but_not_tier_a": True,
        }
    )
    tiers = result.setdefault("opportunity_tiers", {}).setdefault("policy", {})
    tiers.update(
        {
            "tier_a_requires_primary_or_licensed_quote": True,
            "yahoo_is_not_primary_confirmation": True,
        }
    )
    return result


def install_phase62_quality_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    phase62_policy._apply_stock_tiers = _downgrade_stock_a_without_primary_quote
    phase62_policy._tier_contract = _tier_contract_with_primary_quote
    phase62_policy.apply_phase62_overlay = _apply_with_quality_policy
    _INSTALLED = True
