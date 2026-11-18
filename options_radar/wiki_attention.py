"""Investor-attention context for leading U.S. companies and indices from Wikipedia pageviews.

Source: Wikimedia Analytics (AQS) per-article pageviews, English Wikipedia, human users only.
Licence: CC0 1.0 (AQS documentation), so derived numbers may be shown publicly with the source.

What it is: how many people opened the company's Wikipedia article yesterday, compared with
the median of the previous 60 days. Research literature treats this as an attention proxy
with mixed predictive results, so it is context only: never a price signal, never a
recommendation, and never mixed with price data. Standard library only (loaded by path).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any
from urllib.parse import quote

SCHEMA = "ghazi.wiki_attention.v1"
# /per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
API = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
       "{title}/daily/{start}/{end}")
ARTICLE = "https://en.wikipedia.org/wiki/{title}"
# Wikimedia User-Agent policy: "Name/version (contact URL or e-mail) library". A request that does
# not identify its client is put in the most restricted rate-limit tier (keyed on the shared runner IP).
USER_AGENT = "GHAZI-RADAR-wiki-attention/1.0 (https://github.com/GHAZMOTIEBIPRO/GHAZIBOT) python-urllib/3"
BASELINE_DAYS = 60
MIN_BASELINE_POINTS = 40

# Reviewed English-Wikipedia article titles (canonical, no redirects). U.S. market only.
LEADERS: dict[str, tuple[str, str]] = {
    "SPX": ("S&P_500", "مؤشر S&P 500"),
    "NDX": ("Nasdaq-100", "مؤشر ناسداك 100"),
    "DJI": ("Dow_Jones_Industrial_Average", "مؤشر داو جونز الصناعي"),
    "VIX": ("VIX", "مؤشر التقلب VIX"),
    "NVDA": ("Nvidia", "إنفيديا"),
    "AAPL": ("Apple_Inc.", "أبل"),
    "MSFT": ("Microsoft", "مايكروسوفت"),
    "AMZN": ("Amazon_(company)", "أمازون"),
    "GOOGL": ("Alphabet_Inc.", "ألفابت (جوجل)"),
    "META": ("Meta_Platforms", "ميتا"),
    "TSLA": ("Tesla,_Inc.", "تسلا"),
    "AVGO": ("Broadcom", "برودكوم"),
    "BRK.B": ("Berkshire_Hathaway", "بيركشاير هاثاواي"),
    "JPM": ("JPMorgan_Chase", "جي بي مورغان"),
    "LLY": ("Eli_Lilly_and_Company", "إيلي ليلي"),
    "V": ("Visa_Inc.", "فيزا"),
    "MA": ("Mastercard", "ماستركارد"),
    "UNH": ("UnitedHealth_Group", "يونايتد هيلث"),
    "XOM": ("ExxonMobil", "إكسون موبيل"),
    "COST": ("Costco", "كوستكو"),
    "WMT": ("Walmart", "وولمارت"),
    "NFLX": ("Netflix", "نتفليكس"),
    "AMD": ("AMD", "إيه إم دي"),
    "ORCL": ("Oracle_Corporation", "أوراكل"),
    "PLTR": ("Palantir_Technologies", "بالانتير"),
    "INTC": ("Intel", "إنتل"),
    "CRM": ("Salesforce", "سيلزفورس"),
    "ADBE": ("Adobe_Inc.", "أدوبي"),
    "QCOM": ("Qualcomm", "كوالكوم"),
    "MU": ("Micron_Technology", "مايكرون"),
    "BA": ("Boeing", "بوينغ"),
    "DIS": ("The_Walt_Disney_Company", "ديزني"),
    "PFE": ("Pfizer", "فايزر"),
}

LEVELS = (  # (minimum ratio, code, Arabic label), checked from the top
    (3.0, "VERY_HIGH", "مرتفع جدًا"),
    (1.75, "HIGH", "مرتفع"),
    (0.6, "NORMAL", "عادي"),
    (0.0, "LOW", "منخفض"),
)


def window(today: date) -> tuple[date, date]:
    """Request window: BASELINE_DAYS + 8 days ending yesterday (today's data is not complete)."""
    end = today - timedelta(days=1)
    return end - timedelta(days=BASELINE_DAYS + 8), end


def url_for(title: str, start: date, end: date) -> str:
    return API.format(title=quote(title, safe=""), start=start.strftime("%Y%m%d00"), end=end.strftime("%Y%m%d00"))


def parse_items(payload: Any) -> dict[str, int]:
    """{YYYY-MM-DD: views} from an AQS per-article response; malformed rows are dropped."""
    out: dict[str, int] = {}
    items = payload.get("items") if isinstance(payload, dict) else None
    for row in items if isinstance(items, list) else []:
        if not isinstance(row, dict):
            continue
        stamp, views = str(row.get("timestamp") or ""), row.get("views")
        if len(stamp) >= 8 and stamp[:8].isdigit() and isinstance(views, int) and views >= 0:
            out[f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"] = views
    return out


def level_for(ratio: float) -> tuple[str, str]:
    for minimum, code, label in LEVELS:
        if ratio >= minimum:
            return code, label
    return "LOW", "منخفض"


def summarize(symbol: str, series: dict[str, int]) -> dict[str, Any]:
    """Latest day vs the median of the previous BASELINE_DAYS days, and the 7-day average."""
    title, name_ar = LEADERS[symbol]
    row: dict[str, Any] = {"symbol": symbol, "name_ar": name_ar, "title": title,
                           "url": ARTICLE.format(title=quote(title, safe="(),_."))}
    days = sorted(series)
    if len(days) < MIN_BASELINE_POINTS + 1:
        return {**row, "status": "INSUFFICIENT_HISTORY", "have_days": len(days), "need_days": MIN_BASELINE_POINTS + 1}
    latest = days[-1]
    baseline_days = days[-(BASELINE_DAYS + 1):-1]
    base = median(series[d] for d in baseline_days)
    last7 = [series[d] for d in days[-7:]]
    if base <= 0:
        return {**row, "status": "NO_BASELINE", "latest_date": latest}
    ratio = series[latest] / base
    code, label = level_for(ratio)
    return {**row, "status": "OK", "latest_date": latest, "latest_views": series[latest],
            "baseline_median": round(base, 1), "baseline_days": len(baseline_days),
            "ratio_1d": round(ratio, 2), "avg_7d": round(sum(last7) / len(last7), 1),
            "ratio_7d": round((sum(last7) / len(last7)) / base, 2), "level": code, "level_ar": label}


def build(rows: list[dict[str, Any]], *, errors: dict[str, str], now: datetime) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "OK"]
    through = max((r["latest_date"] for r in ok), default=None)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "data_through": through,
        "source": {"name": "Wikimedia Analytics — English Wikipedia pageviews (human users)",
                   "url": "https://wikimedia.org/api/rest_v1/", "license": "CC0 1.0"},
        "method": {"baseline": f"median of the previous {BASELINE_DAYS} days", "agent": "user",
                   "levels": {code: minimum for minimum, code, _ in LEVELS}},
        "rows": sorted(rows, key=lambda r: (r.get("status") != "OK", -(r.get("ratio_1d") or 0), r["symbol"])),
        "errors": dict(sorted(errors.items())),
        "is_price_signal": False,
        "research_only": True,
        "decision_authority": False,
        "note_ar": ("عدد زيارات صفحة الشركة على ويكيبيديا الإنجليزية مقارنة بوسيط 60 يومًا: مؤشر اهتمام وسياق فقط، "
                    "وليس إشارة سعر ولا توصية."),
    }
