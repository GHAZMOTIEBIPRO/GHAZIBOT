from __future__ import annotations

from typing import Any

from . import phase61_overlay

_CONTEXT_ONLY = {"FINRA Reg SHO"}
_MARKET_HINTS = (
    "yahoo", "yfinance", "tiingo", "finnhub", "polygon", "massive",
    "alpaca", "tradier", "twelve data", "marketdata", "iex", "sip",
)
_ORIGINAL_APPLY = phase61_overlay.apply_phase61_overlay


def _is_market_source(value: str) -> bool:
    text = str(value or "").lower()
    return any(hint in text for hint in _MARKET_HINTS)


def _upgrade_stocks(payload: dict[str, Any], intelligence: dict[str, Any]) -> None:
    evidence = intelligence.get("stocks", {}) or {}
    stock_map = {
        str(row.get("symbol") or "").upper(): row
        for row in payload.get("stocks", []) or []
    }
    for item in payload.get("stock_recommendations", []) or []:
        symbol = str(item.get("symbol") or "").upper()
        external = evidence.get(symbol, {}) or {}
        extra = list(external.get("sources") or [])
        social = [x for x in extra if x in phase61_overlay._SOCIAL_PROVIDERS]
        context = [x for x in extra if x in _CONTEXT_ONLY]
        external_directional = [
            x for x in extra
            if x not in phase61_overlay._SOCIAL_PROVIDERS and x not in _CONTEXT_ONLY
        ]
        base = list(item.get("confirmed_sources") or [])
        base_market = [x for x in base if _is_market_source(x)]
        base_directional = [x for x in base if not _is_market_source(x)]
        external_market = list(external.get("market_sources") or [])
        official_directional = [
            x for x in list(external.get("official_sources") or [])
            if x not in _CONTEXT_ONLY
        ]
        market = phase61_overlay._merge_unique(base_market, external_market)
        directional = phase61_overlay._merge_unique(
            base_directional, external_directional, official_directional
        )
        confirmed = phase61_overlay._merge_unique(market, directional)
        cross_confirmed = len(market) >= 2 or (len(market) >= 1 and bool(directional))

        stock = stock_map.get(symbol, {})
        score = float(stock.get("score") or item.get("score") or 0.0)
        entry_state = str(stock.get("entry_state") or "")
        strong = bool(stock.get("new_stock_setup")) and score >= 74 and entry_state in {"confirmed", "early"}
        if strong and cross_confirmed:
            decision = "مرشح بحثي مشروط بعد تحقق المنطقة"
        elif score >= 68 and cross_confirmed:
            decision = "مراقبة بحثية لاختراق أو كسر مؤكد"
        elif "استبعاد" in str(item.get("decision")):
            decision = "استبعاد حاليًا"
        else:
            decision = "مراقبة فقط — يحتاج تأكيدًا اتجاهيًا إضافيًا"

        social_score = float(external.get("social_score") or 0.0)
        confidence = float(item.get("confidence") or 0.0)
        confidence += min(3.0, social_score * 0.12)
        if official_directional:
            confidence += 4.0
        if cross_confirmed:
            confidence += 3.0
        item.update(
            {
                "decision": decision,
                "confidence": round(min(95.0, confidence), 1),
                "source_count": len(confirmed),
                "confirmed_sources": confirmed,
                "cross_source_confirmed": cross_confirmed,
                "market_source_count": len(market),
                "directional_confirmation_sources": directional,
                "official_sources": official_directional,
                "supporting_context_sources": context,
                "social_sources": social,
                "social_score": social_score,
                "external_evidence": external,
            }
        )
        stock["external_evidence"] = external
        stock["supporting_context_sources"] = context


def _apply(payload: dict[str, Any], settings: Any = None) -> dict[str, Any]:
    result = _ORIGINAL_APPLY(payload, settings)
    result.setdefault("recommendation_policy", {}).update(
        {
            "finra_daily_short_volume_is_context_only": True,
            "finra_daily_short_volume_is_not_short_interest": True,
            "finra_cannot_promote_a_candidate_alone": True,
            "directional_confirmation_required": True,
        }
    )
    return result


def install_phase61_policy_fix() -> None:
    phase61_overlay._upgrade_stock_recommendations = _upgrade_stocks
    phase61_overlay.apply_phase61_overlay = _apply
