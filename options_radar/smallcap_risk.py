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
OFFERING_PROSPECTUS = {"424B4", "424B5"}  # final prospectus / shelf supplement: primary OR resale - read the text
RESALE_OR_OTHER = {"424B3", "424B7"}       # usually resale, merger or updated prospectus: not a new issuance

# Dilution evidence only (audit, RELEASE GATE): registration -> capacity -> announced offering -> sale reported.
# A filing type alone never proves a new issuance; only an 8-K item 3.02 reports a completed unregistered sale.
DILUTION_AR = {
    "SHELF_REGISTERED": "تسجيل رف S-3/F-3: قدرة على الإصدار لاحقاً، ليس إصداراً",
    "REGISTRATION_FILED": "تسجيل S-1/F-1: طرح أو إعادة بيع محتمل — يُقرأ النص، ليس إصداراً مؤكداً",
    "OFFERING_PROSPECTUS": "نشرة 424B4/424B5: طرح معلن بموجب تسجيل، أولي أو إعادة بيع — يُقرأ النص قبل الحكم",
    "RESALE_OR_OTHER_PROSPECTUS": "نشرة 424B3/424B7: غالباً إعادة بيع أو معاملة أخرى، لا تعني إصداراً جديداً",
    "UNREGISTERED_SALE_REPORTED": "8-K بند 3.02: بيع أسهم غير مسجل أُبلغ عنه (إصدار حدث)",
}
OTHER_AR = {  # not dilution: listed apart
    "LISTING_DEFICIENCY": "8-K بند 3.01: إشعار عدم استيفاء شروط الإدراج",
    "CHARTER_AMENDMENT": "8-K بند 5.03: تعديل النظام الأساسي (قد يكون تقسيماً عكسياً — يُراجع النص)",
}
RANK_LAST = ("ISSUANCE_REPORTED", "OFFERING_ANNOUNCED")
STATUS_AR = {"UNKNOWN": "التخفيف غير مفحوص (SEC غير متاح)",
             "ISSUANCE_REPORTED": "إصدار أُبلغ عنه",
             "OFFERING_ANNOUNCED": "طرح معلن (أولي أو إعادة بيع — غير محسوم)",
             "CAPACITY_ONLY": "قدرة على الإصدار فقط (تسجيل)",
             "NO_RELEVANT_FILING_FOUND_180D": "لم يُعثر على تسجيل أو طرح في SEC خلال 180 يوماً — لا يعني الأمان"}


def _kinds(form: str, items: str) -> tuple[list[str], list[str]]:
    dilution, other = [], []
    if form in SHELF:
        dilution.append("SHELF_REGISTERED")
    if form in REGISTRATION:
        dilution.append("REGISTRATION_FILED")
    if form in OFFERING_PROSPECTUS:
        dilution.append("OFFERING_PROSPECTUS")
    if form in RESALE_OR_OTHER:
        dilution.append("RESALE_OR_OTHER_PROSPECTUS")
    if form in ("8-K", "8-K/A"):
        codes = set(re.findall(r"\d\.\d\d", items))
        if "3.02" in codes:
            dilution.append("UNREGISTERED_SALE_REPORTED")
        other += [k for k, c in (("LISTING_DEFICIENCY", "3.01"), ("CHARTER_AMENDMENT", "5.03")) if c in codes]
    return dilution, other


def classify(payload: dict[str, Any], *, as_of: date) -> tuple[dict[str, dict], dict[str, dict]]:
    """(dilution evidence, other risks) by kind; only filings available on or before as_of."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms, dates = recent.get("form") or [], recent.get("filingDate") or []
    items, accessions = recent.get("items") or [], recent.get("accessionNumber") or []
    dil: dict[str, dict[str, str]] = {}
    oth: dict[str, dict[str, str]] = {}
    since = (as_of - timedelta(days=WINDOW_DAYS)).isoformat()
    for i, form in enumerate(forms):
        filed = dates[i] if i < len(dates) else ""
        if not filed or filed < since or filed > as_of.isoformat():
            continue
        d, o = _kinds(form, str(items[i] if i < len(items) else ""))
        for target, kinds in ((dil, d), (oth, o)):
            for k in kinds:
                if k not in target or filed > target[k]["filed"]:
                    target[k] = {"filed": filed, "accession": accessions[i] if i < len(accessions) else ""}
    return dil, oth


def shares_outstanding(facts: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any] | None:
    """Latest cover-page shares outstanding filed by as_of, with its date (not the float).

    Several values for the latest date (share classes) or no date -> None (UNKNOWN), never summed or guessed.
    Not split-adjusted: a later reverse split makes it stale (the caller flags 5.03 amendments).
    """
    units = (((facts.get("facts") or {}).get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}
    cutoff = as_of.isoformat() if as_of else "9999"
    points = [p for p in units.get("shares") or [] if p.get("val") and p.get("end") and (p.get("filed") or "") <= cutoff]
    if not points:
        return None
    last_end = max(p["end"] for p in points)
    latest = [p for p in points if p["end"] == last_end]
    if len({p["val"] for p in latest}) > 1:
        return None
    p = max(latest, key=lambda x: x.get("filed", ""))
    return {"shares": int(p["val"]), "as_of": p["end"], "filed": p.get("filed"), "form": p.get("form")}


def assess(submissions: dict[str, Any] | None, facts: dict[str, Any] | None, *, as_of: date) -> dict[str, Any]:
    if submissions:
        dil, oth = classify(submissions, as_of=as_of)
        status = ("ISSUANCE_REPORTED" if "UNREGISTERED_SALE_REPORTED" in dil else
                  "OFFERING_ANNOUNCED" if "OFFERING_PROSPECTUS" in dil else
                  "CAPACITY_ONLY" if dil else "NO_RELEVANT_FILING_FOUND_180D")
    else:
        dil, oth, status = {}, {}, "UNKNOWN"
    return {"dilution": status, "filings": dil, "other_risks": oth,
            "shares_outstanding": shares_outstanding(facts, as_of=as_of) if facts else None,
            "float_shares": "UNKNOWN", "halt_status": "UNKNOWN", "opportunity_confirmed": False}


def line_ar(a: dict[str, Any]) -> str:
    parts = [STATUS_AR[a["dilution"]]]
    parts += [f"{DILUTION_AR[k]} ({v['filed']})" for k, v in sorted(a.get("filings", {}).items())]
    parts += [f"خطر آخر: {OTHER_AR[k]} ({v['filed']})" for k, v in sorted(a.get("other_risks", {}).items())]
    s = a.get("shares_outstanding")
    parts.append(f"الأسهم القائمة {s['shares']:,} حتى {s['as_of']} (ليست الأسهم الحرة؛ قبل أي تقسيم لاحق)" if s
                 else "الأسهم القائمة غير متاحة")
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
