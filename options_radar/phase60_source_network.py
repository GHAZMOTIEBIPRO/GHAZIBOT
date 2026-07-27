from __future__ import annotations

from typing import Any

from .settings import Settings


def _attempt_sets(
    audit: dict[str, Any], section: str
) -> tuple[set[str], dict[str, str]]:
    success: set[str] = set()
    failures: dict[str, str] = {}
    rows = audit.get(section, {})
    if not isinstance(rows, dict):
        return success, failures
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


def _entry(
    name: str,
    category: str,
    role: str,
    configured: bool,
    success: set[str],
    failures: dict[str, str],
    *,
    official: bool = False,
    aliases: tuple[str, ...] = (),
    freshness: str = "حسب صلاحية الحساب",
    note: str = "",
    fixed_status: str | None = None,
) -> dict[str, Any]:
    keys = {name.lower(), *(alias.lower() for alias in aliases)}
    used = any(key in success for key in keys)
    error = next((failures[key] for key in keys if key in failures), None)
    if fixed_status:
        status = fixed_status
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
    stock_success, stock_failures = _attempt_sets(audit, "stocks")
    option_success, option_failures = _attempt_sets(audit, "options")
    operational = payload.get("operational_status", {}) or {}
    sec_status = operational.get("sec_fulltext_status", {}) or {}
    sec_available = bool(sec_status.get("available"))
    sec_message = str(sec_status.get("message") or "")

    stocks = [
        _entry(
            "sec", "official_events",
            "إفصاحات EDGAR والقوائم المالية وForm 4 و13D ومخاطر التخفيف",
            True,
            stock_success | ({"sec"} if sec_available else set()),
            {**stock_failures, **({"sec": sec_message} if sec_message and not sec_available else {})},
            official=True,
            freshness="رسمي حسب نشر EDGAR",
            note="الحظر المؤقت لا يوقف بقية الرادار، وحد الوصول الرسمي لا يتجاوز 10 طلبات/ثانية.",
        ),
        _entry(
            "openfda", "official_events", "قرارات ومعلومات FDA الدوائية",
            True, stock_success, stock_failures, official=True,
            freshness="رسمي؛ المفتاح اختياري لرفع الحصة",
        ),
        _entry("tiingo", "stocks", "شموع وأسعار الأسهم", bool(settings.tiingo_api_key), stock_success, stock_failures),
        _entry("finnhub", "stocks", "شموع وأسعار وأحداث سوقية حسب الخطة", bool(settings.finnhub_api_key), stock_success, stock_failures),
        _entry(
            "tradier", "stocks", "أسعار وشموع من حساب Tradier",
            bool(settings.tradier_token), stock_success, stock_failures,
            freshness="Sandbox متأخر 15 دقيقة" if "sandbox" in settings.tradier_base_url else "حسب حساب الوساطة",
        ),
        _entry(
            "alpaca", "stocks", "شموع IEX أو SIP حسب صلاحية الحساب",
            bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            stock_success, stock_failures, freshness=f"Alpaca {settings.alpaca_stock_feed}",
        ),
        _entry("polygon", "stocks", "شموع وسجل سوقي من Polygon", bool(settings.polygon_api_key), stock_success, stock_failures),
        _entry(
            "twelve_data", "stocks", "شموع احتياطية ضمن حصة الحساب",
            bool(settings.twelve_data_api_key), stock_success, stock_failures,
            aliases=("twelve", "twelvedata"),
        ),
        _entry(
            "alpha_vantage", "stocks", "شموع وبيانات سوقية احتياطية",
            bool(settings.alpha_vantage_api_key), stock_success, stock_failures,
            aliases=("alpha", "alphavantage"),
        ),
        _entry(
            "yahoo", "stocks", "احتياط مجاني غير رسمي للأسعار والشموع",
            True, stock_success, stock_failures, aliases=("yfinance",),
            freshness="قد يكون متأخرًا أو ناقصًا",
            note="لا يسمح وحده برفع توصية إلى درجة قوية.",
        ),
    ]

    options = [
        _entry(
            "tradier", "options", "سلاسل عقود وBid/Ask وحجم وOpen Interest",
            bool(settings.tradier_token), option_success, option_failures,
            freshness=(
                "Sandbox متأخر 15 دقيقة ولا يوفر Greeks من المزود"
                if "sandbox" in settings.tradier_base_url else "حسب حساب الوساطة"
            ),
        ),
        _entry(
            "marketdata", "options", "سلسلة عقود وGreeks وOI وفق صلاحية OPRA",
            bool(settings.marketdata_token), option_success, option_failures,
            freshness="لحظي أو 15 دقيقة أو يوم سابق حسب الاستحقاق",
        ),
        _entry(
            "alpaca", "options", "إثراء آخر صفقة وآخر Quote وGreeks",
            bool(settings.alpaca_api_key and settings.alpaca_secret_key),
            option_success, option_failures,
            freshness="OPRA رسمي عند الاشتراك؛ indicative مجاني متأخر ومعدل",
        ),
        _entry(
            "finnhub", "options", "سلسلة أو Bid/Ask حسب صلاحية الحساب",
            bool(settings.finnhub_api_key), option_success, option_failures,
        ),
        _entry(
            "yahoo", "options", "احتياط غير رسمي لسلسلة العقود",
            True, option_success, option_failures, aliases=("yfinance",),
            freshness="قد يكون متأخرًا؛ لا يثبت Sweep أو Buy-to-Open",
            note="لا يسمح وحده بتوصية عقد قوية.",
        ),
        _entry(
            "polygon_options", "options",
            "OPRA trades/quotes المجمعة من بورصات الخيارات الأمريكية",
            bool(settings.polygon_api_key), option_success, option_failures,
            freshness="بحسب خطة Polygon وترخيص OPRA",
            note="الموصل يحتاج صلاحية Options API قبل تفعيله.",
            fixed_status="entitlement_required",
        ),
        _entry(
            "alpha_vantage_options", "options", "Realtime/Historical options وGreeks",
            bool(settings.alpha_vantage_api_key), option_success, option_failures,
            freshness="واجهة الخيارات اللحظية مدفوعة",
            fixed_status="premium_connector",
        ),
    ]

    return {
        "policy": {
            "strong_recommendation_min_independent_sources": 2,
            "direct_site_scraping": False,
            "opra_exchange_coverage": "عبر مزود OPRA مرخص بدل كشط مواقع Cboe وNasdaq وNYSE وMIAX منفردة.",
            "single_source_cap": 65,
        },
        "summary": {
            "active_stock_sources": sum(item["used_successfully"] for item in stocks),
            "active_option_sources": sum(item["used_successfully"] for item in options),
            "configured_stock_sources": sum(item["configured"] for item in stocks),
            "configured_option_sources": sum(item["configured"] for item in options),
        },
        "stocks": stocks,
        "options": options,
    }
