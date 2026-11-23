"""Server-side plans and entitlements.

The browser only renders what the API returns; every limit and feature below is
checked on the server before the action runs. Prices are the hypotheses from the
PR #424 specification and are shown as such; no plan is sold in this alpha.
"""
from __future__ import annotations

from dataclasses import dataclass

PLAN_ORDER = ("free", "plus", "pro")


@dataclass(frozen=True)
class Plan:
    code: str
    name_ar: str
    price_hypothesis_sar: str
    max_watchlists: int
    max_symbols_per_watchlist: int
    max_datasets: int
    backtests_per_day: int
    features: frozenset[str]


PLANS: dict[str, Plan] = {
    "free": Plan("free", "مجاني", "0", 1, 10, 1, 3,
                 frozenset({"dashboard", "watchlists", "research_center", "analysis"})),
    "plus": Plan("plus", "بحث بلس", "49–99 شهريًا (فرضية تسعير)", 5, 50, 5, 25,
                 frozenset({"dashboard", "watchlists", "research_center", "analysis", "backtest_lab",
                            "data_export"})),
    "pro": Plan("pro", "بحث برو", "149–249 شهريًا (فرضية تسعير)", 20, 200, 20, 200,
                frozenset({"dashboard", "watchlists", "research_center", "analysis", "backtest_lab",
                           "data_export", "backtest_oos_split", "backtest_cost_sensitivity"})),
}

FEATURE_AR = {
    "dashboard": "لوحة التحكم",
    "watchlists": "قوائم المراقبة",
    "research_center": "مركز الأبحاث",
    "analysis": "تحليل سهم على بياناتك",
    "backtest_lab": "مختبر الاختبارات التاريخية",
    "data_export": "تصدير النتائج",
    "backtest_oos_split": "تقسيم داخل/خارج العينة",
    "backtest_cost_sensitivity": "حساسية التكاليف والانزلاق",
}


class EntitlementError(Exception):
    """Raised when the user's plan does not include the action (HTTP 402/403)."""

    def __init__(self, message_ar: str, *, feature: str | None = None, limit: str | None = None):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.feature = feature
        self.limit = limit


def effective_plan(subscription: dict | None, role: str) -> Plan:
    """Admins get every feature; a lapsed subscription falls back to free (fail closed)."""
    if role == "admin":
        return PLANS["pro"]
    if not subscription:
        return PLANS["free"]
    if subscription.get("status") not in ("active", "grace"):
        return PLANS["free"]
    return PLANS.get(subscription.get("plan") or "", PLANS["free"])


def require_feature(plan: Plan, feature: str) -> None:
    if feature not in plan.features:
        raise EntitlementError(f"هذه الميزة ({FEATURE_AR.get(feature, feature)}) غير مشمولة في خطة {plan.name_ar}.",
                               feature=feature)


def require_below(count: int, limit: int, label_ar: str, limit_code: str) -> None:
    if count >= limit:
        raise EntitlementError(f"وصلت إلى حد خطتك: {label_ar} ({limit}).", limit=limit_code)


def plan_public(plan: Plan) -> dict:
    return {"code": plan.code, "name_ar": plan.name_ar, "price_hypothesis_sar": plan.price_hypothesis_sar,
            "limits": {"watchlists": plan.max_watchlists, "symbols_per_watchlist": plan.max_symbols_per_watchlist,
                       "datasets": plan.max_datasets, "backtests_per_day": plan.backtests_per_day},
            "features": sorted(plan.features),
            "features_ar": [FEATURE_AR[f] for f in sorted(plan.features)]}
