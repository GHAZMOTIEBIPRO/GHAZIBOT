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
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.catalyst_watchlist.v1"
MAX_TICKERS = 40
MAX_CATALYSTS = 6
MAX_EVENTS = 400
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
    "ACQUISITION_OR_DISPOSITION_REVIEW": ("MERGER_OR_ACQUISITION", "HIGH", "إتمام استحواذ أو بيع أصول (8-K 2.01)"),
    "MERGER_REGISTRATION_REVIEW": ("MERGER_OR_ACQUISITION", "HIGH", "تسجيل/مراسلات اندماج (S-4 / 425)"),
    "ACTIVIST_STAKE_REVIEW": ("ACTIVIST_STAKE", "MEDIUM", "حصة نشطة تتجاوز 5% (SC 13D)"),
}
FDA_KIND = {"APPROVAL_ORIGINAL": "FDA_APPROVAL", "APPROVAL_SUPPLEMENT": "FDA_SUPPLEMENT", "RECALL": "FDA_RECALL"}
# Review-priority points per catalyst; documented in the payload. They rank
# what to read first and say nothing about price direction.
POINTS = {"HIGH": 35, "MEDIUM": 22, "LOW": 8}
NEW_MOLECULE_BONUS = 10
RELIABILITY = {"exact_normalised_name": 1.0, "issuer_cik": 1.0, "reviewed_sponsor_alias": 0.9,
               "reviewed_issuer_link": 0.9}
RISK_KINDS = {"DILUTION_RISK": "خطر تخفيف", "CHARTER_OR_REVERSE_SPLIT_REVIEW": "تقسيم عكسي/تعديل نظام محتمل",
              "LISTING_NOTICE": "إشعار إدراج (خطر شطب)",
              "FR_AIRWORTHINESS_DIRECTIVE": "توجيه صلاحية طيران إلزامي (FAA)",
              "FR_FTC_CONSENT_ORDER": "تسوية مقترحة مع FTC"}
# Reference list of issuers known to be large. It is NOT a measurement: an
# issuer on it is labelled KNOWN_LARGE_ISSUER_LIST (market cap unverified),
# and an SEC filer status other than "Large accelerated filer" is reported in
# list_review.
KNOWN_LARGE_ISSUERS = frozenset({
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "AMD", "ORCL", "BAC", "CVX", "OXY",
    "LLY", "ABBV", "MRK", "PFE", "JNJ", "BMY", "AMGN", "GILD", "TMO", "ABT", "DHR", "MDT", "UNH", "CVS", "REGN",
    "VRTX", "ISRG", "AZN", "NVS", "GSK", "SNY", "NVO", "BIIB", "ZTS", "SYK", "BSX", "MU", "JPM", "WMT", "COST",
    # Large and mid-cap health-care issuers seen in the FDA / ClinicalTrials
    # feeds (production 2026-10-25 listed several as small-cap candidates).
    "TAK", "BNTX", "MRNA", "BAX", "TEVA", "VTRS", "INCY", "JAZZ", "EXEL", "NBIX", "SRPT", "ALNY", "ILMN",
    "IQV", "HUM", "CI", "ELV", "MCK", "COR", "CAH", "HCA", "GEHC", "RMD", "IDXX", "DXCM", "EW", "ZBH",
    "ALGN", "WST", "MTD", "WAT", "BDX", "CRL", "UTHR", "BMRN", "ARGX", "BGNE", "ONC", "HLN", "PODD",
})


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
    updated = fda.get("source_last_updated") if isinstance(fda.get("source_last_updated"), dict) else {}
    for key in ("approvals", "recalls"):
        # openFDA's dataset update date: the event was available there by then.
        # It is not a per-event publication time.
        source_updated = _day(updated.get(key))
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
                        "source_updated": source_updated,
                        "issuer": str(row.get("sponsor") or row.get("firm") or "")[:80] or None,
                        "match_method": row.get("match_method"),
                        "new_molecule": bool(re.match(r"Type [12]\b", str(row.get("submission_class") or "")))})
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


def clinical_available(report: Any, now: datetime) -> bool:
    if not isinstance(report, dict):
        return False
    produced = _parse(report.get("generated_at"))
    if (report.get("schema") != "ghazi.clinical_registry_feed.v1"
            or report.get("status") not in {"OK", "PARTIAL"}
            or report.get("research_only") is not True
            or report.get("decision_authority") is not False
            or report.get("execution_authority") is not False
            or produced is None or not timedelta(0) <= now - produced <= timedelta(hours=48)):
        return False
    return isinstance(report.get("events"), list)


def clinical_catalysts(report: Any, now: datetime) -> list[dict[str, Any]]:
    if not clinical_available(report, now):
        return []
    events = report.get("events")
    if not isinstance(events, list):
        return []
    result = []
    for event in events[:750]:
        if (not isinstance(event, dict) or event.get("source") != "ClinicalTrials.gov"
                or event.get("kind") not in {"TRIAL_RESULTS_POSTED", "TRIAL_STATUS_REVIEW", "TRIAL_REGISTRY_UPDATE"}
                or event.get("importance") not in RANK
                or event.get("official_registry_only") is not True
                or event.get("outcome_direction") != "NOT_INFERRED"
                or event.get("match_method") not in {"exact_normalised_name", "reviewed_sponsor_alias"}
                or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,7}", str(event.get("symbol", "")))
                or not re.fullmatch(r"https://clinicaltrials[.]gov/study/NCT[0-9]{8}", str(event.get("source_url", "")))):
            continue
        day = _day(event.get("date"))
        if day and (now.date() - timedelta(days=14)).isoformat() <= day <= now.date().isoformat():
            # The registry's own update date is when the change became public there.
            result.append({**event, "source_updated": _day(event.get("registry_updated_date")) or day,
                           "issuer": str(event.get("lead_sponsor") or "")[:80] or None})
    return result


def fr_catalysts(fr: Any) -> list[dict[str, Any]]:
    """Federal Register documents whose named company has a reviewed link (scripts/build_federal_register_feed.py)."""
    out: list[dict[str, Any]] = []
    if not isinstance(fr, dict) or fr.get("schema") != "ghazi.federal_register_feed.v1":
        return out
    for e in fr.get("linked") or []:
        url = str(e.get("source_url") or "")
        day = _day(e.get("date"))
        if not url.startswith("https://www.federalregister.gov/") or day is None or e.get("kind") not in IMPACT:
            continue
        if e.get("importance") not in RANK:
            continue
        for link in e.get("links") or []:
            ticker = str(link.get("ticker") or "")
            if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,7}", ticker):
                continue
            out.append({"symbol": ticker, "kind": e["kind"], "date": day, "importance": e["importance"],
                        "label": f"{e.get('agency')}: {link.get('name')}"[:120], "reason": str(e.get("title") or "")[:200],
                        "source": "Federal Register", "source_url": url, "source_updated": day,
                        "issuer": str(link.get("name") or "")[:80] or None, "match_method": "reviewed_issuer_link",
                        "link_relation": link.get("relation"), "listed_company": link.get("listed_company")})
    return out


def event_key(item: dict[str, Any]) -> str:
    return "|".join(str(item.get(k) or "") for k in ("symbol", "kind", "date", "source_url", "label"))


FIRST_SEEN_VERSION = 2


def first_seen(items: list[dict[str, Any]], previous: Any, now: datetime) -> str:
    """When each event first appeared in our published list (our detection, not the event).

    Carried from the previous published file once tracking is running. On the
    run that starts tracking (a previous file without the current tracking
    version), every event already in the window gets first_seen_at = None
    (basis BEFORE_TRACKING): the source feeds held them before this list did,
    so stamping them with this run's time would claim a detection that did not
    happen now. Only events that appear after tracking started get a time.
    Returns the time tracking started.
    """
    tracking = (isinstance(previous, dict) and previous.get("first_seen_version") == FIRST_SEEN_VERSION
                and isinstance(previous.get("events"), list))
    if not tracking:
        for item in items:
            item["first_seen_at"] = None
            item["first_seen_basis"] = "BEFORE_TRACKING"
        return now.isoformat()
    known = {event_key(old): old.get("first_seen_at") for old in previous["events"] if isinstance(old, dict)}
    for item in items:
        key = event_key(item)
        if key in known:
            item["first_seen_at"] = known[key]
            item["first_seen_basis"] = "CARRIED" if known[key] else "BEFORE_TRACKING"
        else:
            item["first_seen_at"] = now.isoformat()
            item["first_seen_basis"] = "THIS_RUN"
    return str(previous.get("first_seen_tracking_since") or now.isoformat())


def price_band(symbol: str, prices: Any, now: datetime) -> dict[str, Any]:
    """Under-$10 only from a current quote whose source permits public display."""
    quote = (prices.get("quotes") or {}).get(symbol) if isinstance(prices, dict) else None
    unverified = {"price_band": "UNVERIFIED", "sub10_confirmed": False, "reason": "NO_PERMITTED_CURRENT_QUOTE"}
    if not isinstance(quote, dict) or quote.get("public_display_permitted") is not True:
        return unverified
    quoted = _parse(quote.get("quote_time"))
    price = quote.get("price")
    if quoted is None or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return {**unverified, "reason": "QUOTE_INCOMPLETE"}
    if not timedelta(0) <= now - quoted <= timedelta(minutes=MAX_QUOTE_AGE_MIN):
        return {**unverified, "reason": "QUOTE_STALE"}
    band = "UNDER_10" if price < SUB10_LIMIT else "10_OR_MORE"
    return {"price_band": band, "sub10_confirmed": band == "UNDER_10", "reason": "CURRENT_PERMITTED_QUOTE",
            "quote_time": quoted.isoformat(), "source": quote.get("source")}


def score_entry(items: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Review priority 0-100 from strength x recency x reliability of the top three catalysts."""
    parts = []
    for item in items:
        age = max(0, (now.date() - date.fromisoformat(item["date"])).days)
        recency = max(0.0, 1 - age / MAX_EVENT_AGE_DAYS)
        reliability = RELIABILITY.get(str(item.get("match_method")), 0.8)
        points = POINTS[item["importance"]] + (NEW_MOLECULE_BONUS if item.get("new_molecule") else 0)
        parts.append(points * (0.4 + 0.6 * recency) * reliability)
    risks = sorted({RISK_KINDS[x["kind"]] for x in items if x["kind"] in RISK_KINDS}
                   | ({"سحب منتج Class I"} if any(x["kind"] == "FDA_RECALL" and x["importance"] == "HIGH"
                                                    for x in items) else set()))
    newest = min(max(0, (now.date() - date.fromisoformat(x["date"])).days) for x in items)
    return {"catalyst_score": round(min(100.0, sum(sorted(parts, reverse=True)[:3])), 1),
            "days_since_latest": newest, "risk_flags": risks,
            "risk_level": "HIGH" if risks else "NORMAL"}


# SEC public float (dei:EntityPublicFloat on the annual-report cover) is a
# dollar value measured at the second fiscal quarter end; after this many
# days it is flagged stale (one annual measurement plus filing time).
MAX_FLOAT_AGE_DAYS = 470


def _sec_url(value: Any) -> str | None:
    url = str(value or "")
    return url if url.startswith("https://www.sec.gov/") else None


def company_size(symbol: str, sizes: Any, now: datetime) -> dict[str, Any]:
    """Separate size evidence. Market cap stays unverified without a permitted price.

    SEC filing thresholds are a disclosure regime, not a market-cap class, so
    no "small cap" label is derived from them.
    """
    row = (sizes.get("symbols") or {}).get(symbol) if isinstance(sizes, dict) else None
    row = row if isinstance(row, dict) else {}
    out: dict[str, Any] = {
        "universe": "KNOWN_LARGE_ISSUER_LIST" if symbol in KNOWN_LARGE_ISSUERS else "MARKET_CAP_UNVERIFIED",
        "market_cap": {"status": "UNVERIFIED", "reason": "no permitted current price"},
        "float_shares": {"status": "UNAVAILABLE"},
        "public_float_value": None, "shares_outstanding": None, "sec_filer_status": None,
    }
    pf = row.get("public_float_value")
    if isinstance(pf, dict):
        value, as_of, url = pf.get("usd"), _day(pf.get("as_of")), _sec_url(pf.get("source_url"))
        if (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                and as_of and url):
            age = (now.date() - date.fromisoformat(as_of)).days
            if age >= 0:
                out["public_float_value"] = {"usd": float(value), "as_of": as_of, "source_url": url,
                                             "stale": age > MAX_FLOAT_AGE_DAYS}
    so = row.get("shares_outstanding")
    if isinstance(so, dict) and isinstance(so.get("shares"), int) and so["shares"] > 0 and _day(so.get("as_of")) \
            and _sec_url(so.get("source_url")):
        out["shares_outstanding"] = {"shares": so["shares"], "as_of": _day(so.get("as_of")),
                                     "source_url": _sec_url(so.get("source_url"))}
    fs = row.get("sec_filer_status")
    if isinstance(fs, dict) and isinstance(fs.get("category"), str) and fs["category"].strip():
        out["sec_filer_status"] = {"category": fs["category"].strip()[:60],
                                   "smaller_reporting_company": fs.get("smaller_reporting_company") is True,
                                   "exchanges": [str(x)[:20] for x in fs.get("exchanges") or []][:3],
                                   "source_url": _sec_url(fs.get("source_url"))}
    return out


# What an event is, independent of its review priority. A registry edit is
# administrative; posted results say nothing about direction until read.
IMPACT = {"FDA_APPROVAL": "REGULATORY_DECISION", "FDA_SUPPLEMENT": "REGULATORY_DECISION_MINOR",
          "FDA_RECALL": "RISK", "DILUTION_RISK": "RISK", "CHARTER_OR_REVERSE_SPLIT_REVIEW": "RISK",
          "LISTING_NOTICE": "RISK", "TRIAL_RESULTS_POSTED": "RESULTS_POSTED_DIRECTION_UNKNOWN",
          "TRIAL_STATUS_REVIEW": "STATUS_CHANGE", "TRIAL_REGISTRY_UPDATE": "ADMINISTRATIVE",
          "FR_PRIORITY_REVIEW_VOUCHER": "REGULATORY_DECISION", "FR_APPROVAL_WITHDRAWN": "STATUS_CHANGE",
          "FR_AIRWORTHINESS_DIRECTIVE": "RISK", "FR_PROPOSED_AIRWORTHINESS_DIRECTIVE": "STATUS_CHANGE",
          "FR_SPECIAL_CONDITIONS": "STATUS_CHANGE", "FR_FTC_CONSENT_ORDER": "RISK",
          "FR_ENERGY_REGULATORY_FILING": "STATUS_CHANGE", "FR_NUCLEAR_LICENSE_ACTION": "STATUS_CHANGE"}


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per underlying event (same kind and official link): the latest wins."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (str(item.get("kind")), str(item.get("source_url") or item.get("label") or id(item)))
        if key not in latest or str(item.get("date")) > str(latest[key].get("date")):
            latest[key] = item
    return list(latest.values())


def build(fda: Any, sec: Any, prices: Any, now: datetime, clinical: Any = None,
          sizes: Any = None, previous: Any = None, fr: Any = None) -> dict[str, Any]:
    cutoff = (now - timedelta(days=MAX_EVENT_AGE_DAYS)).date().isoformat()
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []
    for item in dedupe(fda_catalysts(fda) + sec_catalysts(sec) + clinical_catalysts(clinical, now)
                       + fr_catalysts(fr)):
        if cutoff <= item["date"] <= now.date().isoformat():
            events.append({**item, "impact": IMPACT.get(item["kind"], "OTHER")})
    tracking_since = first_seen(events, previous, now)
    for item in events:
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
            **score_entry(items, now),
            **price_band(symbol, prices, now),
            "price_confirmed_signal": False,
            **company_size(symbol, sizes, now),
        })
        band = entries[-1]["price_band"]
        entries[-1]["candidate_status"] = ("PRICE_VERIFICATION_NEEDED" if band == "UNVERIFIED" else
                                           "UNDER_10_CONFIRMED" if band == "UNDER_10" else "NOT_UNDER_10")
    # Rank by review priority; fewer risk flags first on ties.
    entries.sort(key=lambda e: (-e["catalyst_score"], len(e["risk_flags"]), -RANK[e["highest_importance"]],
                                e["days_since_latest"]))
    sec_used = isinstance(sec, dict) and str(sec.get("status")) in SEC_OK
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "status": "AVAILABLE" if entries else "NO_RECENT_CATALYSTS",
        "window_days": MAX_EVENT_AGE_DAYS,
        "sources": {"openfda": isinstance(fda, dict),
                    "sec_edgar": sec_used,
                    "sec_status": sec.get("status") if isinstance(sec, dict) else "MISSING",
                    "clinicaltrials": clinical_available(clinical, now),
                    "clinicaltrials_status": clinical.get("status") if isinstance(clinical, dict) else "MISSING",
                    "federal_register": isinstance(fr, dict) and fr.get("schema") == "ghazi.federal_register_feed.v1"},
        "watchlist": entries[:MAX_TICKERS],
        # Every matched event in the window (the watchlist keeps MAX_CATALYSTS per
        # ticker), newest first, with three separate times: the event date, the
        # source's own update date, and when this list first showed the event.
        "events": sorted(events, key=lambda e: (e["date"], RANK[e["importance"]]), reverse=True)[:MAX_EVENTS],
        "first_seen_version": FIRST_SEEN_VERSION,
        "first_seen_tracking_since": tracking_since,
        "event_time_fields": {
            "date": "event date (FDA action date; registry update date for ClinicalTrials.gov)",
            "source_updated": "openFDA dataset update date, or the registry record's update date; not a per-event"
                              " publication time for openFDA",
            "first_seen_at": "first time this list showed the event; null = listed before tracking began",
        },
        # Market cap needs a permitted price; until then nothing is called small or
        # large from SEC data. Low price (price_band) is a separate test.
        "market_cap_unverified_candidates": [e["symbol"] for e in entries[:MAX_TICKERS]
                                             if e["universe"] == "MARKET_CAP_UNVERIFIED"],
        "public_float_ranked": sorted(
            ({"symbol": e["symbol"], "usd": e["public_float_value"]["usd"], "as_of": e["public_float_value"]["as_of"]}
             for e in entries[:MAX_TICKERS] if e.get("public_float_value") and not e["public_float_value"]["stale"]),
            key=lambda r: r["usd"]),
        # The reference list is a manual exclusion; SEC filer status that
        # contradicts it is surfaced for review rather than silently trusted.
        "list_review": [{"symbol": e["symbol"], "sec_filer_status": e["sec_filer_status"]["category"]}
                        for e in entries[:MAX_TICKERS]
                        if e["symbol"] in KNOWN_LARGE_ISSUERS and e.get("sec_filer_status")
                        and e["sec_filer_status"]["category"].lower() != "large accelerated filer"],
        "size_rules": {
            "market_cap": "UNVERIFIED: shares outstanding x a current price from a permitted source (none configured)",
            "public_float_value": "SEC dei:EntityPublicFloat: USD held by non-affiliates at the second fiscal quarter end;"
                                  " not market cap and not a share count",
            "shares_outstanding": "SEC dei:EntityCommonStockSharesOutstanding (cover page); not float",
            "float_shares": "UNAVAILABLE: no permitted source",
            "sec_filer_status": "SEC submissions filer category; a disclosure regime, not a market-cap class",
            "known_large_issuer_list": "manual reference list used only to exclude obvious large issuers; reviewed"
                                       " against SEC filer status",
            "public_float_max_age_days": MAX_FLOAT_AGE_DAYS,
            "sources_status": "AVAILABLE" if isinstance(sizes, dict) and sizes.get("symbols") else "SEC_SIZE_DATA_UNAVAILABLE",
            "note_ar": ("التصنيف السوقي غير متحقق: القيمة السوقية تحتاج سعرًا حاليًا من مصدر مسموح. قيمة Public Float "
                        "من SEC بالدولار وتصنيف الإفصاح أدلة منفصلة، وليست تصنيف Small Cap. انخفاض السعر اختبار منفصل."),
        },
        "ranking_rules": {
            "points": POINTS, "new_molecule_bonus": NEW_MOLECULE_BONUS,
            "recency": "x (0.4 + 0.6 * (1 - age_days / 30))", "reliability": RELIABILITY,
            "top_n": 3, "tie_break": "fewer risk flags first",
            "note_ar": "الدرجة أولوية مراجعة للمحفز الرسمي، وليست توقعًا لاتجاه السعر أو احتمال ربح.",
        },
        "price_confirmed_signals": [],
        "price_confirmation": {
            "status": "NO_PERMITTED_PRICE_SOURCE",
            "rule": f"under ${SUB10_LIMIT:.0f} only from a quote <= {MAX_QUOTE_AGE_MIN} min old with public display rights",
            "note_ar": "لا نصنّف أي سهم تحت 10$ ولا نؤكد إشارة سعرية دون سعر حديث من مصدر يسمح بالنشر.",
        },
        "clinical_registry_attribution": "Courtesy of the U.S. National Library of Medicine",
        "clinical_registry_database_license": "ODbL-1.0",
        "notes_ar": ["سجلات ClinicalTrials.gov لا تثبت نجاح العلاج أو اتجاه السعر؛ لا تأييد من NLM وقد لا تعكس آخر تعديل.","قائمة متابعة محفزات رسمية وليست توصيات ولا إشارات دخول.",
                     "أهمية المحفز تعني أولوية المراجعة، لا اتجاه السعر."],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fda", type=Path, required=True)
    parser.add_argument("--sec", type=Path)
    parser.add_argument("--clinical", type=Path)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--sizes", type=Path, help="SEC public-float file; absent until SEC access works")
    parser.add_argument("--federal-register", type=Path, help="scripts/build_federal_register_feed.py output")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path, help="previous published watchlist (default: --output before it is"
                                                         " replaced); carries each event's first_seen_at")
    args = parser.parse_args()
    previous = _load(args.previous or args.output)
    report = build(_load(args.fda), _load(args.sec), _load(args.prices), datetime.now(timezone.utc),
                   _load(args.clinical), _load(args.sizes), previous, _load(args.federal_register))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Catalyst watchlist:", json.dumps({"status": report["status"], "tickers": len(report["watchlist"]),
                                             "sources": report["sources"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
