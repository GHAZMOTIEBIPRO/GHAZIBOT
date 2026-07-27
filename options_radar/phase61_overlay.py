from __future__ import annotations

from typing import Any

from .phase60_overlay import apply_phase60_overlay
from .phase61_intelligence import collect_phase61_intelligence
from .settings import Settings

_SOCIAL_PROVIDERS = {"X recent search", "Reddit communities"}


def _audit_map(intelligence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("provider")): row
        for row in intelligence.get("audit", []) or []
        if isinstance(row, dict) and row.get("provider")
    }


def _network_entry(
    name: str,
    category: str,
    role: str,
    audit: dict[str, Any],
    *,
    official: bool = False,
    note: str = "",
) -> dict[str, Any]:
    configured = bool(audit.get("configured"))
    success = bool(audit.get("success"))
    if success:
        status = "active"
    elif configured and audit.get("error"):
        status = "configured_error"
    elif configured:
        status = "configured_waiting"
    else:
        status = "needs_key"
    return {
        "name": name,
        "category": category,
        "role": role,
        "official": official,
        "configured": configured,
        "used_successfully": success,
        "status": status,
        "freshness": "حسب صلاحية المصدر والخطة",
        "note": note,
        "last_error": audit.get("error"),
        "records": int(audit.get("records") or 0),
    }


def _extend_network(payload: dict[str, Any], intelligence: dict[str, Any]) -> None:
    network = payload.setdefault("source_network", {})
    stocks = network.setdefault("stocks", [])
    options = network.setdefault("options", [])
    audits = _audit_map(intelligence)
    existing_stock = {str(item.get("name")) for item in stocks if isinstance(item, dict)}
    existing_option = {str(item.get("name")) for item in options if isinstance(item, dict)}

    additions_stock = [
        _network_entry(
            "finra_reg_sho",
            "official_short_data",
            "حجم البيع على المكشوف اليومي المبلّغ إلى مرافق FINRA",
            audits.get("finra_reg_sho", {}),
            official=True,
            note="بيانات رسمية مساندة؛ لا تعني وحدها اتجاهًا هابطًا.",
        ),
        _network_entry(
            "alpha_vantage_news",
            "news_sentiment",
            "أخبار مرتبطة بالرمز ودرجة توجه الخبر",
            audits.get("alpha_vantage_news", {}),
        ),
        _network_entry(
            "x_recent_search",
            "community",
            "بحث X الرسمي عن Cashtags والحسابات السوقية المحددة",
            audits.get("x_recent_search", {}),
            note="إضارة اهتمام فقط؛ لا تُستخدم وحدها للترقية إلى دخول.",
        ),
        _network_entry(
            "reddit_oauth_search",
            "community",
            "بحث OAuth داخل مجتمعات الأسهم والعقود الأمريكية",
            audits.get("reddit_oauth_search", {}),
            note="إشارة اهتمام فقط مع إزالة التكرار؛ لا تُستخدم وحدها للترقية.",
        ),
        _network_entry(
            "alpaca_stock_snapshots",
            "stocks",
            "Snapshot مستقل للأسهم من IEX أو SIP حسب الاشتراك",
            audits.get("alpaca_stock_snapshots", {}),
        ),
    ]
    additions_options = [
        _network_entry(
            "benzinga_option_activity",
            "options_flow",
            "نشاط خيارات غير اعتيادي مع التنفيذ عند Ask/Bid والبريميوم",
            audits.get("benzinga_option_activity", {}),
        ),
        _network_entry(
            "alpaca_option_snapshots",
            "options",
            "آخر Quote/Trade وGreeks للعقود عبر OPRA أو Indicative",
            audits.get("alpaca_option_snapshots", {}),
            note="Indicative مجاني متأخر ومعدل؛ OPRA يحتاج اشتراكًا.",
        ),
    ]
    stocks.extend(item for item in additions_stock if item["name"] not in existing_stock)
    options.extend(item for item in additions_options if item["name"] not in existing_option)
    summary = network.setdefault("summary", {})
    summary["active_stock_sources"] = sum(bool(item.get("used_successfully")) for item in stocks if isinstance(item, dict))
    summary["active_option_sources"] = sum(bool(item.get("used_successfully")) for item in options if isinstance(item, dict))
    summary["configured_stock_sources"] = sum(bool(item.get("configured")) for item in stocks if isinstance(item, dict))
    summary["configured_option_sources"] = sum(bool(item.get("configured")) for item in options if isinstance(item, dict))
    policy = network.setdefault("policy", {})
    policy.update(
        {
            "community_sources_are_supporting_only": True,
            "licensed_api_and_official_api_only": True,
            "no_direct_exchange_or_social_scraping": True,
        }
    )


def _merge_unique(*values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for rows in values:
        for value in rows:
            text = str(value or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
    return result


def _upgrade_stock_recommendations(payload: dict[str, Any], intelligence: dict[str, Any]) -> None:
    evidence = intelligence.get("stocks", {}) or {}
    stock_map = {str(row.get("symbol") or "").upper(): row for row in payload.get("stocks", []) or []}
    for recommendation in payload.get("stock_recommendations", []) or []:
        symbol = str(recommendation.get("symbol") or "").upper()
        external = evidence.get(symbol, {}) or {}
        extra_sources = list(external.get("sources") or [])
        social_sources = [source for source in extra_sources if source in _SOCIAL_PROVIDERS]
        non_social_sources = [source for source in extra_sources if source not in _SOCIAL_PROVIDERS]
        official_sources = list(external.get("official_sources") or [])
        market_sources = list(external.get("market_sources") or [])
        base_sources = list(recommendation.get("confirmed_sources") or [])
        confirmed_sources = _merge_unique(base_sources, market_sources, non_social_sources)
        source_count = len(confirmed_sources)
        market_source_count = len(_merge_unique(base_sources, market_sources))
        official_confirmation = bool(official_sources)
        cross_confirmed = market_source_count >= 2 or (market_source_count >= 1 and official_confirmation)
        stock = stock_map.get(symbol, {})
        score = float(stock.get("score") or recommendation.get("score") or 0.0)
        entry_state = str(stock.get("entry_state") or "")
        strong = bool(stock.get("new_stock_setup")) and score >= 74 and entry_state in {"confirmed", "early"}
        if strong and cross_confirmed:
            decision = "دخول مشروط بعد تحقق منطقة الدخول"
        elif score >= 68 and cross_confirmed:
            decision = "مراقبة لاختراق أو كسر مؤكد"
        elif "استبعاد" in str(recommendation.get("decision")):
            decision = "استبعاد حاليًا"
        else:
            decision = "مراقبة فقط — يحتاج تأكيد سوقي أو رسمي إضافي"
        social_score = float(external.get("social_score") or 0.0)
        confidence = min(95.0, float(recommendation.get("confidence") or 0.0) + min(5.0, social_score * 0.2) + (4.0 if official_confirmation else 0.0))
        recommendation.update(
            {
                "decision": decision,
                "confidence": round(confidence, 1),
                "source_count": source_count,
                "confirmed_sources": confirmed_sources,
                "cross_source_confirmed": cross_confirmed,
                "market_source_count": market_source_count,
                "official_sources": official_sources,
                "social_sources": social_sources,
                "social_score": social_score,
                "external_evidence": external,
            }
        )
        stock["social_score"] = social_score
        stock["external_evidence"] = external


def _upgrade_contract_recommendations(payload: dict[str, Any], intelligence: dict[str, Any]) -> None:
    evidence = intelligence.get("contracts", {}) or {}
    contract_map = {
        str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", ""): row
        for row in list(payload.get("top_calls", []) or []) + list(payload.get("top_puts", []) or [])
    }
    for recommendation in payload.get("contract_recommendations", []) or []:
        contract_symbol = str(recommendation.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
        external = evidence.get(contract_symbol, {}) or {}
        base_sources = list(recommendation.get("confirmed_sources") or [])
        flow_sources = list(external.get("market_flow_sources") or [])
        confirmed_sources = _merge_unique(base_sources, flow_sources)
        market_flow_source_count = len(confirmed_sources)
        contract = contract_map.get(contract_symbol, {})
        flow_score = float(contract.get("flow_momentum_score") or recommendation.get("flow_score") or 0.0)
        aggressive = contract.get("buying_flow_type") == "Aggressive Buying"
        unusual = bool(contract.get("unusual_activity_flag"))
        cross_confirmed = market_flow_source_count >= 2
        if cross_confirmed and aggressive and unusual and flow_score >= 72:
            decision = "عقد مرشح لدخول مشروط بعد تحقق السعر"
        elif cross_confirmed and unusual and flow_score >= 62:
            decision = "مراقبة عقد مع انتظار Ask-side جديد"
        elif "استبعاد" in str(recommendation.get("decision")):
            decision = "استبعاد حاليًا"
        else:
            decision = "مراقبة فقط — يحتاج مصدر Flow/OPRA ثانٍ"
        confidence = float(recommendation.get("confidence") or 0.0)
        if cross_confirmed:
            confidence = min(95.0, confidence + 7.0)
        recommendation.update(
            {
                "decision": decision,
                "confidence": round(confidence, 1),
                "source_count": market_flow_source_count,
                "confirmed_sources": confirmed_sources,
                "cross_source_confirmed": cross_confirmed,
                "market_flow_source_count": market_flow_source_count,
                "external_evidence": external,
            }
        )
        contract["external_evidence"] = external


def apply_phase61_overlay(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    payload = apply_phase60_overlay(payload, settings)
    intelligence = collect_phase61_intelligence(payload, settings)
    payload["intelligence"] = intelligence
    _upgrade_stock_recommendations(payload, intelligence)
    _upgrade_contract_recommendations(payload, intelligence)
    _extend_network(payload, intelligence)
    payload["schema_version"] = 6
    payload["phase"] = "6.1"
    payload["model_version"] = "2026.07-phase6.1-intelligence"
    summary = payload.setdefault("summary", {})
    summary["stock_recommendations"] = sum(
        "دخول مشروط" in str(item.get("decision"))
        for item in payload.get("stock_recommendations", []) or []
    )
    summary["contract_recommendations"] = sum(
        "دخول مشروط" in str(item.get("decision"))
        for item in payload.get("contract_recommendations", []) or []
    )
    summary["external_sources_successful"] = intelligence.get("summary", {}).get("successful_sources", 0)
    summary["social_mentions"] = intelligence.get("summary", {}).get("social_mentions", 0)
    payload["recommendation_policy"].update(
        {
            "social_sources_support_only": True,
            "option_recommendation_requires_two_market_or_flow_sources": True,
            "stock_recommendation_requires_market_plus_market_or_official_confirmation": True,
        }
    )
    payload["disclaimer"] = (
        "رادار الأسهم ورادار العقود منفصلان. X وReddit يقيسان الاهتمام فقط ولا يصدران قرار شراء. "
        "ترقية السهم تتطلب تأكيدًا سوقيًا متعددًا أو سعرًا مع دليل رسمي مستقل، وترقية العقد تتطلب "
        "مصدرين مستقلين من بيانات العقود أو Flow. لا يوجد تنفيذ آلي أو ضمان ربح."
    )
    return payload
