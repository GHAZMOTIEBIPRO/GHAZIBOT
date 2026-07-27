from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .settings import Settings

SOURCE_AUDIT_PATH = Path("data/live/source_audit.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _attempt_sets(audit: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    success: set[str] = set()
    failures: dict[str, str] = {}
    for section in ("stocks", "options"):
        rows = audit.get(section, {})
        if not isinstance(rows, dict):
            continue
        for item in rows.values():
            if not isinstance(item, dict):
                continue
            for attempt in item.get("attempts", []) or []:
                if not isinstance(attempt, dict):
                    continue
                provider = str(attempt.get("provider") or "").strip().lower()
                if not provider:
                    continue
                if attempt.get("success"):
                    success.add(provider)
                elif attempt.get("error"):
                    failures.setdefault(provider, str(attempt.get("error")))
    return success, failures


def _source_entry(
    *,
    name: str,
    category: str,
    role: str,
    official: bool,
    configured: bool,
    success: set[str],
    failures: dict[str, str],
    aliases: tuple[str, ...] = (),
    freshness: str = "حسب صلاحية الحساب",
    note: str = "",
    integration: str = "active_connector",
) -> dict[str, Any]:
    keys = {name.lower(), *(alias.lower() for alias in aliases)}
    used = any(key in success for key in keys)
    error = next((failures[key] for key in keys if key in failures), None)
    if integration != "active_connector":
        status = integration
    elif used:
        status = "active"
    elif configured and error:
        status = "configured_error"
    elif configured:
        status = "configured_waiting"
    elif name.lower() in {"yahoo", "sec", "openfda"}:
        status = "available"
    else:
        status = "needs_key"
    return {
        "name": name,
        "category": category,
        "role": role,
        "official": official,
        "configured": configured,
        "used_successfully": used,
        "status": status,
        "freshness": freshness,
        "note": note,
        "last_error": error,
    }


def build_source_network(
    settings: Settings,
    payload: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    success, failures = _attempt_sets(audit)
    operational = payload.get("operational_status", {}) or {}
    sec_status = operational.get("sec_fulltext_status", {}) or {}
    sec_available = bool(sec_status.get("available"))
    sec_note = str(sec_status.get("message") or "")

    stocks = [
        _source_entry(
            name="sec",
            category="official_events",
            role="إفصاحات، قوائم مالية، Form 4 و13D ومخاطر التخفيف",
            official=True,
            configured=True,
            success=success | ({"sec"} if sec_available else set()),
            failures={**failures, **({"sec": sec_note} if sec_note and not sec_available else {})},
            freshness="رسمي حسب نشر EDGAR",
            note="حد SEC الرسمي الأقصى 10 طلبات/ثانية؛ الحظر المؤقت لا يوقف بقية الرادار.",
        ),
        _source_entry(
            name="openfda",
            category="official_events",
            role="قرارات ومعلومات FDA الدوائية",
            official=True,
            configured=True,
            success=success,
            failures=failures,
            freshness="رسمي؛ المفتاح اختياري لرفع الحصة",
        ),
        _source_entry(
            name="tiingo",
            category="stocks",
            role="شموع وأسعار الأسهم",
            official=False,
            configured=bool(settings.tiingo_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="finnhub",
            category="stocks",
            role="شموع وأسعار وأحداث سوقية حسب الخطة",
            official=False,
            configured=bool(settings.finnhub_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="tradier",
            category="stocks",
            role="أسعار وشموع من حساب Tradier",
            official=False,
            configured=bool(settings.tradier_token),
            success=success,
            failures=failures,
            freshness=(
                "Sandbox متأخر 15 دقيقة"
                if "sandbox" in settings.tradier_base_url
                else "حسب صلاحية حساب الوساطة"
            ),
        ),
        _source_entry(
            name="alpaca",
            category="stocks",
            role="شموع IEX أو SIP حسب صلاحية الحساب",
            official=False,
            configured=bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            success=success,
            failures=failures,
            freshness=f"Alpaca {settings.alpaca_stock_feed}",
        ),
        _source_entry(
            name="polygon",
            category="stocks",
            role="شموع وسجل سوقي من API Polygon",
            official=False,
            configured=bool(settings.polygon_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="twelve_data",
            aliases=("twelve", "twelvedata"),
            category="stocks",
            role="شموع احتياطية ضمن حصة الحساب",
            official=False,
            configured=bool(settings.twelve_data_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="alpha_vantage",
            aliases=("alpha", "alphavantage"),
            category="stocks",
            role="شموع وبيانات سوقية احتياطية",
            official=False,
            configured=bool(settings.alpha_vantage_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="yahoo",
            aliases=("yfinance",),
            category="stocks",
            role="احتياط مجاني غير رسمي للأسعار والشموع",
            official=False,
            configured=True,
            success=success,
            failures=failures,
            freshness="قد يكون متأخرًا أو ناقصًا",
            note="لا يسمح وحده برفع توصية إلى درجة قوية.",
        ),
    ]

    options = [
        _source_entry(
            name="tradier",
            category="options",
            role="سلاسل عقود، Bid/Ask، حجم وOpen Interest",
            official=False,
            configured=bool(settings.tradier_token),
            success=success,
            failures=failures,
            freshness=(
                "Sandbox متأخر 15 دقيقة ولا يوفر Greeks من المزود"
                if "sandbox" in settings.tradier_base_url
                else "حسب صلاحية حساب الوساطة"
            ),
        ),
        _source_entry(
            name="marketdata",
            category="options",
            role="سلسلة عقود وGreeks وOI وفق صلاحية OPRA",
            official=False,
            configured=bool(settings.marketdata_token),
            success=success,
            failures=failures,
            freshness="لحظي أو 15 دقيقة أو يوم سابق حسب الاستحقاق",
        ),
        _source_entry(
            name="alpaca",
            category="options",
            role="إثراء آخر صفقة وآخر Quote وGreeks",
            official=False,
            configured=bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            success=success,
            failures=failures,
            freshness=(
                "OPRA رسمي عند الاشتراك؛ indicative مجاني متأخر ومعدل"
            ),
        ),
        _source_entry(
            name="finnhub",
            category="options",
            role="سلسلة أو Bid/Ask حسب صلاحية الحساب",
            official=False,
            configured=bool(settings.finnhub_api_key),
            success=success,
            failures=failures,
        ),
        _source_entry(
            name="yahoo",
            aliases=("yfinance",),
            category="options",
            role="احتياط غير رسمي لسلسلة العقود",
            official=False,
            configured=True,
            success=success,
            failures=failures,
            freshness="قد يكون متأخرًا؛ لا يثبت Sweep أو Buy-to-Open",
            note="لا يسمح وحده بتوصية عقد قوية.",
        ),
        _source_entry(
            name="polygon_options",
            category="options",
            role="OPRA trades/quotes من جميع بورصات الخيارات الأمريكية",
            official=False,
            configured=bool(settings.polygon_api_key),
            success=success,
            failures=failures,
            freshness="بحسب خطة Polygon وترخيص OPRA",
            note="موثق كمصدر OPRA شامل؛ موصل سلسلة العقود سيبقى غير مفعل حتى تتوفر صلاحية Options API.",
            integration="entitlement_required",
        ),
        _source_entry(
            name="alpha_vantage_options",
            category="options",
            role="Realtime/Historical options وGreeks",
            official=False,
            configured=bool(settings.alpha_vantage_api_key),
            success=success,
            failures=failures,
            freshness="واجهة الخيارات اللحظية مدفوعة",
            integration="premium_connector",
        ),
    ]

    active_stock = sum(item["used_successfully"] for item in stocks)
    active_options = sum(item["used_successfully"] for item in options)
    return {
        "policy": {
            "strong_recommendation_min_independent_sources": 2,
            "direct_site_scraping": False,
            "opra_exchange_coverage": "يتم عبر مزود OPRA مرخص بدل كشط Cboe/Nasdaq/NYSE/MIAX منفردة.",
            "single_source_cap": 65,
        },
        "summary": {
            "active_stock_sources": active_stock,
            "active_option_sources": active_options,
            "configured_stock_sources": sum(item["configured"] for item in stocks),
            "configured_option_sources": sum(item["configured"] for item in options),
        },
        "stocks": stocks,
        "options": options,
    }


def _audit_meta(audit: dict[str, Any], section: str, symbol: str) -> dict[str, Any]:
    row = (audit.get(section, {}) or {}).get(symbol, {})
    return row.get("metadata", {}) if isinstance(row, dict) else {}


def _confidence(base_score: float, source_count: int, catalyst_confidence: float = 0.0) -> float:
    raw = 0.72 * base_score + 0.18 * catalyst_confidence * 100.0 + 3.5 * min(source_count, 3)
    cap = 65.0 if source_count < 2 else 82.0 if source_count == 2 else 92.0
    return round(max(0.0, min(cap, raw)), 1)


def build_stock_recommendations(payload: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for stock in payload.get("stocks", []) or []:
        symbol = str(stock.get("symbol") or "").upper()
        meta = _audit_meta(audit, "stocks", symbol)
        sources = list(meta.get("successful_sources") or [])
        source_count = int(meta.get("source_count") or len(sources) or 1)
        confirmed = bool(meta.get("cross_source_confirmed"))
        score = float(stock.get("score") or 0.0)
        catalyst_confidence = float(stock.get("catalyst_confidence") or 0.0)
        confidence = _confidence(score, source_count, catalyst_confidence)
        strong = bool(stock.get("new_stock_setup")) and score >= 74
        entry_state = str(stock.get("entry_state") or "")
        if source_count < 2 or not confirmed:
            decision = "مراقبة فقط — يحتاج تأكيد مصدر ثانٍ"
        elif strong and entry_state in {"confirmed", "early"}:
            decision = "دخول مشروط بعد تحقق منطقة الدخول"
        elif score >= 68:
            decision = "مراقبة لاختراق أو كسر مؤكد"
        else:
            decision = "استبعاد حاليًا"
        recommendations.append(
            {
                "symbol": symbol,
                "side": str(stock.get("setup_side") or "call").upper(),
                "decision": decision,
                "confidence": confidence,
                "source_count": source_count,
                "confirmed_sources": sources,
                "cross_source_confirmed": confirmed,
                "price_dispersion_pct": meta.get("latest_close_dispersion_pct"),
                "entry_low": stock.get("entry_low"),
                "entry_high": stock.get("entry_high"),
                "target_1": stock.get("target_1"),
                "target_2": stock.get("target_2"),
                "invalidation": stock.get("invalidation") or stock.get("stop"),
                "score": stock.get("score"),
                "rating": stock.get("rating"),
                "thesis": stock.get("reasons"),
            }
        )
    return recommendations


def build_contract_recommendations(payload: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    rows = list(payload.get("top_calls", []) or []) + list(payload.get("top_puts", []) or [])
    for contract in rows:
        symbol = str(contract.get("symbol") or "").upper()
        meta = _audit_meta(audit, "options", symbol)
        if not meta:
            provider_row = (payload.get("provider_audit", {}) or {}).get(symbol, {})
            meta = provider_row.get("metadata", {}) if isinstance(provider_row, dict) else {}
        sources = list(meta.get("successful_sources") or [])
        source_count = int(meta.get("source_count") or len(sources) or 1)
        confirmed = bool(meta.get("cross_source_confirmed") or source_count >= 2)
        flow_score = float(contract.get("flow_momentum_score") or 0.0)
        model_score = float(contract.get("score") or 0.0)
        confidence = _confidence(0.65 * flow_score + 0.35 * model_score, source_count)
        aggressive = contract.get("buying_flow_type") == "Aggressive Buying"
        unusual = bool(contract.get("unusual_activity_flag"))
        if source_count < 2 or not confirmed:
            decision = "مراقبة فقط — يحتاج تأكيد مصدر ثانٍ"
        elif aggressive and unusual and flow_score >= 72:
            decision = "عقد مرشح لدخول مشروط بعد تحقق السعر"
        elif unusual and flow_score >= 62:
            decision = "مراقبة عقد مع انتظار Ask-side جديد"
        else:
            decision = "استبعاد حاليًا"
        recommendations.append(
            {
                "contract_symbol": contract.get("contract_symbol"),
                "symbol": symbol,
                "side": str(contract.get("option_type") or "call").upper(),
                "decision": decision,
                "confidence": confidence,
                "source_count": source_count,
                "confirmed_sources": sources,
                "cross_source_confirmed": confirmed,
                "flow_score": contract.get("flow_momentum_score"),
                "model_score": contract.get("score"),
                "vol_to_oi_ratio": contract.get("vol_to_oi_ratio") or contract.get("vol_oi"),
                "volume_spike_ratio": contract.get("volume_spike_ratio"),
                "buying_flow_type": contract.get("buying_flow_type"),
                "entry_price": contract.get("entry_price"),
                "target_1": contract.get("target_1"),
                "target_2": contract.get("target_2"),
                "stop_price": contract.get("stop_price"),
            }
        )
    return recommendations


def apply_phase60_overlay(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    audit = _read_json(SOURCE_AUDIT_PATH)
    for stock in payload.get("stocks", []) or []:
        stock.pop("best_option", None)
    payload["schema_version"] = 6
    payload["phase"] = "6.0"
    payload["model_version"] = "2026.07-phase6-multisource"
    payload["source_audit"] = audit
    payload["source_network"] = build_source_network(settings, payload, audit)
    payload["stock_recommendations"] = build_stock_recommendations(payload, audit)
    payload["contract_recommendations"] = build_contract_recommendations(payload, audit)
    summary = payload.setdefault("summary", {})
    summary["stock_recommendations"] = sum(
        "استبعاد" not in str(item.get("decision"))
        for item in payload["stock_recommendations"]
    )
    summary["contract_recommendations"] = sum(
        "استبعاد" not in str(item.get("decision"))
        for item in payload["contract_recommendations"]
    )
    payload["recommendation_policy"] = {
        "stocks_and_contracts_are_separate": True,
        "minimum_sources_for_strong_recommendation": 2,
        "single_source_output": "watch_only",
        "automatic_order_execution": False,
        "note": "التوصية البحثية القوية لا تظهر إلا بعد تأكيد مصدرين مستقلين؛ مصدر واحد ينتج مراقبة فقط.",
    }
    payload["disclaimer"] = (
        "الرادار يفصل تحليل الأسهم عن تحليل العقود. لا تُرفع أي إشارة إلى توصية بحثية قوية "
        "إلا بعد تأكيد مصدرين مستقلين على الأقل. Ask-side وVol/OI لا يثبتان Buy-to-Open "
        "بشكل قطعي، ولا يوجد تنفيذ آلي أو ضمان ربح."
    )
    return payload
