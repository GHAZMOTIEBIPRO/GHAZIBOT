"""Small-cap risk context from official SEC data: registrations vs actual issuance, share count, splits.

Owner (PHASE 5): a registration is a possibility, not an issuance; shares outstanding are not the float;
an unknown is UNKNOWN, never "no risk". Sources: SEC submissions (form types, filing dates, 8-K item
numbers) and XBRL companyfacts (dei:EntityCommonStockSharesOutstanding with its date). Only with a real
SEC_USER_AGENT and within fair access (two requests per candidate, at most 8 candidates per scan).
Halts are NOT available here: NasdaqTrader's halt feed is closed by its terms (source_permissions) and
the free IEX stream carries no trading-status channel, so halt status is always UNKNOWN on this path.
Nothing here is stored or published; it is attached to the private alert only.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any
from urllib.request import Request, urlopen

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
WINDOW_DAYS = 180
SHELF = {"S-3", "S-3ASR", "F-3", "F-3ASR"}
REGISTRATION = {"S-1", "F-1", "S-1/A", "F-1/A"}
TAKEDOWN = {"424B5", "424B4", "424B3", "424B7"}

RISK_AR = {
    "SHELF_REGISTERED": "تسجيل رف (S-3/F-3): قدرة على الإصدار لاحقاً، ليس إصداراً",
    "REGISTRATION_FILED": "تسجيل S-1/F-1: طرح أو إعادة بيع محتمل، ليس إصداراً مؤكداً",
    "OFFERING_SUPPLEMENT": "نشرة 424B: إصدار فعلي مرجّح بموجب تسجيل قائم",
    "UNREGISTERED_SALE": "8-K بند 3.02: بيع أسهم غير مسجل (إصدار فعلي)",
    "DELISTING_NOTICE": "8-K بند 3.01: إشعار عدم استيفاء شروط الإدراج",
    "CHARTER_AMENDMENT": "8-K بند 5.03: تعديل النظام الأساسي (قد يكون تقسيماً عكسياً — يُراجع)",
}


def classify(payload: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    """Recent dilution-relevant filings by kind, with the latest date and accession for each kind."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms, dates = recent.get("form") or [], recent.get("filingDate") or []
    items, accessions = recent.get("items") or [], recent.get("accessionNumber") or []
    found: dict[str, dict[str, str]] = {}
    since = (as_of - timedelta(days=WINDOW_DAYS)).isoformat()
    for i, form in enumerate(forms):
        filed = dates[i] if i < len(dates) else ""
        if not filed or filed < since or filed > as_of.isoformat():
            continue
        kinds = []
        if form in SHELF:
            kinds.append("SHELF_REGISTERED")
        if form in REGISTRATION:
            kinds.append("REGISTRATION_FILED")
        if form in TAKEDOWN:
            kinds.append("OFFERING_SUPPLEMENT")
        if form in ("8-K", "8-K/A"):
            codes = set(re.findall(r"\d\.\d\d", str(items[i] if i < len(items) else "")))
            kinds += [k for k, c in (("UNREGISTERED_SALE", "3.02"), ("DELISTING_NOTICE", "3.01"),
                                     ("CHARTER_AMENDMENT", "5.03")) if c in codes]
        for k in kinds:
            if k not in found or filed > found[k]["filed"]:
                found[k] = {"filed": filed, "accession": accessions[i] if i < len(accessions) else ""}
    return found


def shares_outstanding(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Latest cover-page shares outstanding with its as-of date (not the float)."""
    units = (((facts.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}
    points = [p for p in units.get("shares") or [] if p.get("val") and p.get("end")]
    if not points:
        return None
    p = max(points, key=lambda x: (x["end"], x.get("filed", "")))
    return {"shares": int(p["val"]), "as_of": p["end"], "filed": p.get("filed"), "form": p.get("form")}


def assess(submissions: dict[str, Any] | None, facts: dict[str, Any] | None, *, as_of: date) -> dict[str, Any]:
    kinds = classify(submissions, as_of=as_of) if submissions else None
    shares = shares_outstanding(facts) if facts else None
    actual = bool(kinds) and any(k in kinds for k in ("OFFERING_SUPPLEMENT", "UNREGISTERED_SALE"))
    return {
        "dilution": "UNKNOWN" if kinds is None else ("ACTUAL_ISSUANCE_LIKELY" if actual else
                                                    "CAPACITY_ONLY" if kinds else "NONE_FILED_180D"),
        "filings": kinds or {}, "shares_outstanding": shares, "float_shares": "UNKNOWN",
        "halt_status": "UNKNOWN", "opportunity_confirmed": False,
    }


def line_ar(a: dict[str, Any]) -> str:
    if a["dilution"] == "UNKNOWN":
        parts = ["التخفيف غير مفحوص (SEC غير مفعّل)"]
    elif a["dilution"] == "NONE_FILED_180D":
        parts = ["لا تسجيل أو إصدار في SEC خلال 180 يوماً (لا يعني انعدام المخاطر)"]
    else:
        parts = [f"{RISK_AR[k]} ({v['filed']})" for k, v in sorted(a["filings"].items())]
    s = a.get("shares_outstanding")
    parts.append(f"الأسهم القائمة {s['shares']:,} حتى {s['as_of']} (ليست الأسهم الحرة)" if s else "الأسهم القائمة غير متاحة")
    parts.append("الأسهم الحرة: غير متاحة؛ التوقف: غير متاح من مصدر مرخص")
    return "؛ ".join(parts)


def fetch(cik: str, user_agent: str, *, opener=urlopen, timeout: float = 10.0) -> tuple[dict | None, dict | None]:
    """Two official requests; any failure (403 included) leaves that part UNKNOWN, never retried around."""
    if "@" not in (user_agent or "") or not str(cik).isdigit():
        return None, None
    out = []
    for url in (SUBMISSIONS, FACTS):
        try:
            req = Request(url.format(cik=str(int(cik)).zfill(10)),
                          headers={"User-Agent": user_agent, "Accept": "application/json"})
            with opener(req, timeout=timeout) as r:
                out.append(json.loads(r.read(20_000_001)))
        except Exception:  # noqa: BLE001 - refusal or outage: UNKNOWN, not a workaround
            out.append(None)
    return out[0], out[1]
