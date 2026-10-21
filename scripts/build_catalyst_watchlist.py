"""Catalyst watchlist from official filings, kept apart from price signals.

A ticker enters the watchlist only through an official, non-price event:
openFDA approvals and recalls (CC0) and, once SEC access works, EDGAR
filings (offerings, charter changes where reverse splits are disclosed,
listing notices, insider statements, material agreements, earnings
releases). Nothing here says the stock is below $10, moving or tradable:

- price_band is UNVERIFIED for every entry. A stock is classed under $10
  only from a quote that has an absolute quote time no older than
  MAX_QUOTE_AGE_MIN, from a source whose terms allow public display; the
  --prices input stays empty until such a source exists.
- price_confirmed_signals is a separate list and stays empty without
  permitted, current bars; a catalyst is never promoted to a signal.

Standard library only; reads published files, makes no requests.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.catalyst_watchlist.v1"
MAX_TICKERS = 40
MAX_CATALYSTS = 6
MAX_EVENT_AGE_DAYS = 30
MAX_QUOTE_AGE_MIN = 20
SUB10_LIMIT = 10.0
RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
# Live EDGAR responses only; the undated bulk-archive fallback is not current.
SEC_OK = {"OK", "PARTIAL"}
# SEC event topic -> (catalyst kind, importance, Arabic label). Importance is
# about how much the event warrants a look, never a price direction.
SEC_TOPICS = {
    "OFFERING_OR_REGISTRATION_TERMS_REVIEW": ("DILUTION_RISK", "HIGH", "إفصاح طرح أو تسجيل أسهم: خطر تخفيف"),
    "UNREGISTERED_EQUITY_SALE_REVIEW": ("DILUTION_RISK", "HIGH", "بيع أسهم غير مسجلة: خطر تخفيف"),
    "SHAREHOLDER_RIGHTS_OR_CHARTER_CHANGE_REVIEW": ("CHARTER_OR_REVERSE_SPLIT_REVIEW", "HIGH",
                                                    "تعديل حقوق المساهمين أو النظام (منها التقسيم العكسي)"),
    "LISTING_STANDARD_NOTICE_REVIEW": ("LISTING_NOTICE", "HIGH", "إشعار معايير الإدراج"),
    "MATERIAL_AGREEMENT_REVIEW": ("MATERIAL_AGREEMENT", "MEDIUM", "اتفاقية جوهرية (عقد)"),
    "EARNINGS_RELEASE_REVIEW": ("EARNINGS_RELEASE", "MEDIUM", "إعلان نتائج"),
    "INSIDER_OWNERSHIP_STATEMENT_REVIEW": ("INSIDER_FILING", "LOW", "إفصاح ملكية مطلعين (Form 3/4/5)"),
    "PERIODIC_FINANCIAL_REPORT_REVIEW": ("PERIODIC_REPORT", "LOW", "تقرير دوري 10-Q/10-K"),
}
FDA_KIND = {"APPROVAL_ORIGINAL": "FDA_APPROVAL", "APPROVAL_SUPPLEMENT": "FDA_SUPPLEMENT", "RECALL": "FDA_RECALL"}


def _load(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when.astimezone(timezone.utc) if when.tzinfo else None


def _day(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def fda_catalysts(fda: Any) -> list[dict[str, Any]]:
    out = []
    if not isinstance(fda, dict):
        return out
    for key in ("approvals", "recalls"):
        for row in fda.get(key) or []:
            if not isinstance(row, dict) or not row.get("ticker") or row.get("importance") not in RANK:
                continue
            day = _day(row.get("date"))
            kind = FDA_KIND.get(str(row.get("event_type")))
            if day is None or kind is None:
                continue
            label = ", ".join(map(str, row.get("products") or [])) or str(row.get("product") or "")[:80]
            out.append({"symbol": str(row["ticker"]), "kind": kind, "date": day, "importance": row["importance"],
                        "label": label[:120], "reason": str(row.get("importance_reason") or "")[:160],
                        "source": "openFDA", "source_url": row.get("official_url"),
                        "match_method": row.get("match_method")})
    return out


def sec_catalysts(sec: Any) -> list[dict[str, Any]]:
    out = []
    if not isinstance(sec, dict) or str(sec.get("status")) not in SEC_OK:
        return out
    for row in sec.get("filings") or []:
        if not isinstance(row, dict) or row.get("original_filing_confirmed") is not True or not row.get("symbol"):
            continue
        day = _day(row.get("filing_date"))
        url = str(row.get("source_url") or "")
        if day is None or not url.startswith("https://www.sec.gov/"):
            continue
        for topic in row.get("event_topics") or []:
            if topic not in SEC_TOPICS:
                continue
            kind, importance, label = SEC_TOPICS[topic]
            out.append({"symbol": str(row["symbol"]), "kind": kind, "date": day, "importance": importance,
                        "label": f"{row.get('form')}: {label}", "reason": topic, "source": "SEC EDGAR",
                        "source_url": url, "match_method": "issuer_cik"})
    return out


def price_band(symbol: str, prices: Any, now: datetime) -> dict[str, Any]:
    """Under-$10 only from a current quote whose source permits public display."""
    quote = (prices.get("quotes") or {}).get(symbol) if isinstance(prices, dict) else None
    unverified = {"price_band": "UNVERIFIED", "sub10_confirmed": False, "reason": "NO_PERMITTED_CURRENT_QUOTE"}
    if not isinstance(quote, dict) or quote.get("public_display_permitted") is not True:
        return unverified
    quoted = _parse(quote.get("quote_time"))
    price = quote.get("price")
    if quoted is None or isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        return {**unverified, "reason": "QUOTE_INCOMPLETE"}
    if not timedelta(0) <= now - quoted <= timedelta(minutes=MAX_QUOTE_AGE_MIN):
        return {**unverified, "reason": "QUOTE_STALE"}
    band = "UNDER_10" if price < SUB10_LIMIT else "10_OR_MORE"
    return {"price_band": band, "sub10_confirmed": band == "UNDER_10", "reason": "CURRENT_PERMITTED_QUOTE",
            "quote_time": quoted.isoformat(), "source": quote.get("source")}


def build(fda: Any, sec: Any, prices: Any, now: datetime) -> dict[str, Any]:
    cutoff = (now - timedelta(days=MAX_EVENT_AGE_DAYS)).date().isoformat()
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in fda_catalysts(fda) + sec_catalysts(sec):
        if item["date"] >= cutoff:
            by_symbol.setdefault(item["symbol"], []).append(item)
    entries = []
    for symbol, items in by_symbol.items():
        items.sort(key=lambda x: (RANK[x["importance"]], x["date"]), reverse=True)
        top = max(RANK[x["importance"]] for x in items)
        entries.append({
            "symbol": symbol,
            "highest_importance": next(k for k, v in RANK.items() if v == top),
            "latest_date": max(x["date"] for x in items),
            "catalyst_count": len(items),
            "dilution_risk": any(x["kind"] == "DILUTION_RISK" for x in items),
            "charter_or_reverse_split_review": any(x["kind"] == "CHARTER_OR_REVERSE_SPLIT_REVIEW" for x in items),
            "catalysts": items[:MAX_CATALYSTS],
            **price_band(symbol, prices, now),
            "price_confirmed_signal": False,
        })
    entries.sort(key=lambda e: (RANK[e["highest_importance"]], e["latest_date"], e["catalyst_count"]), reverse=True)
    sec_used = isinstance(sec, dict) and str(sec.get("status")) in SEC_OK
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "status": "AVAILABLE" if entries else "NO_RECENT_CATALYSTS",
        "window_days": MAX_EVENT_AGE_DAYS,
        "sources": {"openfda": isinstance(fda, dict),
                    "sec_edgar": sec_used,
                    "sec_status": sec.get("status") if isinstance(sec, dict) else "MISSING"},
        "watchlist": entries[:MAX_TICKERS],
        "price_confirmed_signals": [],
        "price_confirmation": {
            "status": "NO_PERMITTED_PRICE_SOURCE",
            "rule": f"under ${SUB10_LIMIT:.0f} only from a quote <= {MAX_QUOTE_AGE_MIN} min old with public display rights",
            "note_ar": "لا نصنّف أي سهم تحت 10$ ولا نؤكد إشارة سعرية دون سعر حديث من مصدر يسمح بالنشر.",
        },
        "notes_ar": ["قائمة متابعة محفزات رسمية وليست توصيات ولا إشارات دخول.",
                     "أهمية المحفز تعني أولوية المراجعة، لا اتجاه السعر."],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fda", type=Path, required=True)
    parser.add_argument("--sec", type=Path)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(_load(args.fda), _load(args.sec), _load(args.prices), datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Catalyst watchlist:", json.dumps({"status": report["status"], "tickers": len(report["watchlist"]),
                                             "sources": report["sources"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
