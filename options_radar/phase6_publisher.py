from __future__ import annotations

import os
import re
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _provider_names(value: Any) -> list[str]:
    if not value:
        return []
    return _unique([
        item.strip()
        for item in re.split(r"[,+|/]", str(value))
        if item.strip()
    ])


def _successful_providers(value: Any) -> set[str]:
    providers: set[str] = set()
    if isinstance(value, dict):
        provider = value.get("provider")
        if provider and value.get("success") is True:
            providers.add(str(provider).lower())
        for child in value.values():
            providers.update(_successful_providers(child))
    elif isinstance(value, list):
        for child in value:
            providers.update(_successful_providers(child))
    return providers


def _source_item(
    name: str,
    role: str,
    *,
    configured: bool,
    active: bool,
    official: bool = False,
    freshness: str = "حسب الخطة والصلاحية",
    note: str = "",
    entitlement: bool = False,
) -> dict[str, Any]:
    if active:
        status = "active"
    elif configured:
        status = "configured_waiting"
    elif entitlement:
        status = "entitlement_required"
    else:
        status = "needs_key"
    return {
        "name": name,
        "role": role,
        "configured": configured,
        "active": active,
        "official": official,
        "freshness": freshness,
        "note": note,
        "status": status,
    }


def build_source_network(payload: dict[str, Any]) -> dict[str, Any]:
    active = _successful_providers(payload.get("provider_audit", {}))
    errors = payload.get("errors", {}) or {}
    sec_status = (payload.get("operational_status", {}) or {}).get("sec_fulltext_status", {}) or {}

    def env(name: str) -> bool:
        return bool(os.getenv(name, "").strip())

    stocks = [
        _source_item("SEC EDGAR", "الإفصاحات الرسمية والمحـفزات والبيانات المالية", configured=True, active=bool(sec_status.get("available")), official=True, freshness="رسمي؛ قد تحجب SEC عناوين GitHub المشتركة", note=str(sec_status.get("message") or "")),
        _source_item("openFDA / Drugs@FDA", "القرارات والتنبيهات الدوائية الرسمية", configured=True, active=not any("openfda" in str(key).lower() for key in errors), official=True, freshness="رسمي"),
        _source_item("U.S. Treasury", "منحنى العائد والسياق الماكروي", configured=True, active=bool(payload.get("macro")), official=True, freshness="رسمي"),
        _source_item("Nasdaq Market Activity", "اكتشاف الأسهم المتحركة وتوسيع الكون", configured=True, active=bool((payload.get("universe_sources", {}) or {}).get("nasdaq_movers")), official=True, freshness="عام؛ ليس تغذية تداول موحدة"),
        _source_item("Tiingo", "شموع وأسعار الأسهم", configured=env("TIINGO_API_KEY"), active="tiingo" in active),
        _source_item("Finnhub", "أسعار وأساسيات وأخبار الأسهم", configured=env("FINNHUB_API_KEY"), active="finnhub" in active, note="بعض نقاط bid/ask تتطلب خطة مدفوعة"),
        _source_item("Polygon / Massive", "SIP للأسهم والأخبار والشموع", configured=env("POLYGON_API_KEY"), active="polygon" in active, note="التغطية والحداثة حسب الخطة"),
        _source_item("Alpaca", "أسعار وquotes للأسهم", configured=env("ALPACA_API_KEY") and env("ALPACA_SECRET_KEY"), active="alpaca" in active),
        _source_item("Twelve Data", "شموع احتياطية للأسهم", configured=env("TWELVE_DATA_API_KEY"), active="twelve_data" in active),
        _source_item("Alpha Vantage", "شموع وبيانات احتياطية", configured=env("ALPHA_VANTAGE_API_KEY"), active="alpha_vantage" in active),
        _source_item("Yahoo/yfinance", "احتياط غير رسمي للأسعار والقوائم", configured=True, active="yahoo" in active or payload.get("stocks") is not None, freshness="غير رسمي وقد يتأخر", note="لا يستخدم وحده لتسمية الفرصة توصية مؤكدة"),
    ]
    options = [
        _source_item("OPRA عبر Polygon / Massive", "تجميع quotes/trades من بورصات الخيارات الأمريكية", configured=env("POLYGON_API_KEY"), active="polygon" in active, freshness="حسب الخطة", note="الطريق النظامي لتغطية Cboe وNasdaq وNYSE وMIAX وغيرها بدل كشط مواقعها", entitlement=True),
        _source_item("Tradier", "سلاسل الخيارات وBid/Ask وOpen Interest", configured=env("TRADIER_TOKEN"), active="tradier" in active, freshness="Sandbox متأخر 15 دقيقة؛ Production حسب صلاحية الحساب"),
        _source_item("Alpaca Options", "إثراء quotes وGreeks عند توفر الصلاحية", configured=env("ALPACA_API_KEY") and env("ALPACA_SECRET_KEY"), active="alpaca" in active, entitlement=True),
        _source_item("MarketData.app", "سلاسل وGreeks اختيارية", configured=env("MARKETDATA_TOKEN"), active="marketdata" in active),
        _source_item("Finnhub", "إثراء سوقي عند توفر endpoint والخطة", configured=env("FINNHUB_API_KEY"), active="finnhub" in active, entitlement=True),
        _source_item("Yahoo/yfinance Options", "احتياط غير رسمي لسلاسل الخيارات", configured=True, active="yahoo" in active or payload.get("options") is not None, freshness="غير رسمي وقد يتأخر", note="لا يثبت sweep أو buy-to-open"),
    ]
    return {
        "policy": {
            "strong_recommendation_min_independent_sources": 2,
            "exchange_site_scraping": False,
            "opra_sip_preferred": True,
            "single_source_decision": "مراقبة فقط",
        },
        "summary": {
            "active_stock_sources": sum(bool(item["active"]) for item in stocks),
            "active_option_sources": sum(bool(item["active"]) for item in options),
            "configured_stock_sources": sum(bool(item["configured"]) for item in stocks),
            "configured_option_sources": sum(bool(item["configured"]) for item in options),
        },
        "stocks": stocks,
        "options": options,
    }


def _stock_recommendation(stock: dict[str, Any]) -> dict[str, Any]:
    sources = ["Yahoo/yfinance market data"]
    catalyst_source = str(stock.get("catalyst_source") or "").strip()
    fundamental_source = str(stock.get("fundamental_source") or "").strip()
    if catalyst_source and "yahoo" not in catalyst_source.lower():
        sources.append(catalyst_source)
    if fundamental_source and fundamental_source.lower() not in {item.lower() for item in sources}:
        sources.append(fundamental_source)
    sources = _unique(sources)
    score = _number(stock.get("score"))
    if len(sources) >= 2 and score >= 70 and stock.get("new_stock_setup"):
        decision = "دخول مشروط"
    elif score >= 60:
        decision = "مرشح للمراقبة"
    else:
        decision = "مراقبة فقط"
    confidence = min(95.0, max(35.0, score * 0.72 + min(len(sources), 3) * 7.0))
    return {
        "symbol": stock.get("symbol"),
        "decision": decision,
        "confidence": round(confidence, 1),
        "source_count": len(sources),
        "confirmed_sources": sources,
        "entry_low": stock.get("entry_low"),
        "entry_high": stock.get("entry_high"),
        "target_1": stock.get("target_1"),
        "target_2": stock.get("target_2"),
        "invalidation": stock.get("invalidation", stock.get("stop")),
    }


def _contract_recommendation(option: dict[str, Any]) -> dict[str, Any]:
    sources = _provider_names(option.get("source"))
    history_source = str(option.get("volume_history_source") or "").strip()
    catalyst_source = str(option.get("catalyst_source") or "").strip()
    if history_source:
        sources.append(history_source)
    if catalyst_source and "yahoo" not in catalyst_source.lower():
        sources.append(catalyst_source)
    sources = _unique(sources or ["Yahoo/yfinance options"])
    flow = _number(option.get("flow_momentum_score"))
    score = _number(option.get("score"))
    unusual = bool(option.get("unusual_activity_flag"))
    if len(sources) >= 2 and unusual and flow >= 65 and score >= 55:
        decision = "دخول مشروط"
    elif unusual and flow >= 50:
        decision = "مرشح للمراقبة"
    else:
        decision = "مراقبة عقد"
    confidence = min(95.0, max(30.0, flow * 0.62 + score * 0.18 + min(len(sources), 3) * 6.0))
    return {
        "contract_symbol": option.get("contract_symbol"),
        "symbol": option.get("symbol"),
        "option_type": option.get("option_type"),
        "decision": decision,
        "confidence": round(confidence, 1),
        "source_count": len(sources),
        "confirmed_sources": sources,
        "entry_price": option.get("entry_price"),
        "target_1": option.get("target_1"),
        "target_2": option.get("target_2"),
        "stop_price": option.get("stop_price"),
    }


def publish_phase6(payload: dict[str, Any]) -> None:
    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    calls = payload.get("top_calls") if isinstance(payload.get("top_calls"), list) else []
    puts = payload.get("top_puts") if isinstance(payload.get("top_puts"), list) else []
    options = calls + puts
    for stock in stocks:
        stock.pop("best_option", None)
    payload["schema_version"] = 6
    payload["phase"] = "6.0"
    payload["model_version"] = "2026.07-phase6-multisource"
    payload["source_network"] = build_source_network(payload)
    payload["stock_recommendations"] = [_stock_recommendation(row) for row in stocks]
    payload["contract_recommendations"] = [_contract_recommendation(row) for row in options]
    summary = payload.setdefault("summary", {})
    summary["stock_recommendations"] = sum(item["decision"] == "دخول مشروط" for item in payload["stock_recommendations"])
    summary["contract_recommendations"] = sum(item["decision"] == "دخول مشروط" for item in payload["contract_recommendations"])
    payload["disclaimer"] = (
        "رادار الأسهم ورادار العقود مستقلان. التوصية القوية تتطلب تأكيد مصدرين مستقلين على الأقل. "
        "تغطية بورصات الخيارات تتم عبر OPRA ومزودي بيانات مرخصين، ولا يتم كشط مواقع البورصات. "
        "موضع الصفقة عند Ask تقدير لضغط الشراء وليس إثبات Buy-to-Open أو ضمانًا للربح."
    )
