"""Company events from the Federal Register (U.S. government publication, public domain).

Agencies: FDA, FAA, FTC, FERC, NRC, NHTSA; last 30 days of documents. For each document
the company named in it is read with a fixed pattern for that document type (e.g. FAA
"Airworthiness Directives; <company> Airplanes", "<company>; Withdrawal of Approval ...",
FTC "<A> and <B>; Analysis of Proposed Consent Order"); priority review vouchers name the
sponsor only in the body, read from the document's raw text.

A company is linked to a ticker only by an exact (normalised) name in the reviewed table
data/issuer_links.json, where each row records the relation (same entity, wholly owned
subsidiary, renamed) and its evidence, or in the reviewed FDA sponsor alias table. No
similarity matching. Joint ventures, partly owned and private companies are listed as
excluded with the reason. Unlinked documents are kept as general notices.

A notice is not a positive catalyst: each kind carries a neutral label, and safety or
enforcement actions are marked as risks.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

SCHEMA = "ghazi.federal_register_feed.v1"
API = "https://www.federalregister.gov/api/v1/documents.json"
AGENCIES = ("food-and-drug-administration", "federal-aviation-administration", "federal-trade-commission",
            "federal-energy-regulatory-commission", "nuclear-regulatory-commission",
            "national-highway-traffic-safety-administration")
AGENCY_AR = {"food-and-drug-administration": "FDA", "federal-aviation-administration": "FAA",
             "federal-trade-commission": "FTC", "federal-energy-regulatory-commission": "FERC",
             "nuclear-regulatory-commission": "NRC", "national-highway-traffic-safety-administration": "NHTSA"}
WINDOW_DAYS = 30
MAX_PAGES = 3
UA = {"User-Agent": "GHAZI-RADAR-federal-register/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
ROOT = Path(__file__).resolve().parents[1]
# Neutral Arabic label, review importance and group per kind. Importance is what to read first, never direction.
KINDS = {
    "FR_PRIORITY_REVIEW_VOUCHER": ("منح قسيمة مراجعة أولوية من FDA", "MEDIUM", "decision"),
    "FR_APPROVAL_WITHDRAWN": ("سحب موافقة تطبيق دوائي (FDA)", "LOW", "status"),
    "FR_AIRWORTHINESS_DIRECTIVE": ("⚠ توجيه صلاحية طيران إلزامي (FAA)", "MEDIUM", "risk"),
    "FR_PROPOSED_AIRWORTHINESS_DIRECTIVE": ("مقترح توجيه صلاحية طيران (FAA)", "LOW", "status"),
    "FR_SPECIAL_CONDITIONS": ("شروط خاصة لاعتماد طراز طائرة (FAA)", "LOW", "status"),
    "FR_FTC_CONSENT_ORDER": ("⚠ تسوية مقترحة مع لجنة التجارة الفيدرالية (FTC)", "MEDIUM", "risk"),
    "FR_ENERGY_REGULATORY_FILING": ("إجراء تنظيمي لدى لجنة تنظيم الطاقة (FERC)", "LOW", "status"),
    "FR_NUCLEAR_LICENSE_ACTION": ("إجراء ترخيص نووي (NRC)", "LOW", "status"),
}
NOISE = re.compile(r"(Agency Information Collection|Sunshine Act|Combined Notice of Filings|Class [A-E] Airspace|"
                   r"Petition for Rulemaking of|Request for Nominations|Advisory Committee; .*Renewal|"
                   r"Civil Penalty Inflation|Privacy Act of 1974)", re.I)
COMPANY = re.compile(r"\b(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|LLC|L\.L\.C\.|L\.P\.|LP|Ltd\.?|"
                     r"Limited|S\.A\.S?\.?|SAS|S\.p\.A\.|GmbH|AG|plc|N\.V\.|Holdings?)\b")


LEGAL_SUFFIX = re.compile(r"(\s+(inc|incorporated|corp|corporation|co|company|llc|l l c|lp|l p|ltd|limited|plc|"
                          r"sa|s a|sas|ag|gmbh|nv|n v))+$")


def norm(name: str) -> str:
    """Case, punctuation and a trailing legal suffix removed; the name itself must match exactly."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"\bet al\.?$", "", s.strip())
    s = re.sub(r"[.,()'’\"]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return LEGAL_SUFFIX.sub("", s).strip()


def entities(doc: dict[str, Any], body: str | None = None) -> tuple[str | None, list[str]]:
    """(kind, company names) read with a fixed pattern for the document type; (None, []) otherwise."""
    title = str(doc.get("title") or "")
    agency = doc.get("agency")
    dtype = doc.get("type")
    if agency == "federal-aviation-administration":
        m = re.match(r"Airworthiness Directives; (.+?) (Airplanes|Helicopters|Engines|Gliders|Balloons|Propellers|"
                     r"Products|Rotorcraft)\b", title)
        if m:
            return ("FR_AIRWORTHINESS_DIRECTIVE" if dtype == "Rule" else "FR_PROPOSED_AIRWORTHINESS_DIRECTIVE",
                    [re.sub(r"\s*\(.*$", "", m.group(1)).strip()])
        m = re.match(r"Special Conditions: (.+?) Model\b", title)
        if m:
            return "FR_SPECIAL_CONDITIONS", [m.group(1).strip()]
        return None, []
    if agency == "federal-trade-commission":
        m = re.match(r"(.+?); Analysis of (Proposed )?(Agreement Containing )?Consent Order", title)
        if m:
            return "FR_FTC_CONSENT_ORDER", [x.strip() for x in re.split(r",\s*| and ", m.group(1)) if x.strip()]
        return None, []
    if agency == "food-and-drug-administration":
        m = re.match(r"(.+?)(?:, U\.S\. Agent for [^;]+)?(?:,? et al\.)?; Withdrawal of Approval", title)
        if m:
            return "FR_APPROVAL_WITHDRAWN", [m.group(1).strip()]
        if title.startswith("Issuance of Priority Review Voucher"):
            # "... issuance of a priority review voucher to <Sponsor>." (sponsor named only in the body)
            m = re.search(r"voucher (?:to|for) ([A-Z][A-Za-z0-9&.,' -]{2,80}?(?:Inc\.|LLC|Ltd\.|Limited|Corporation|"
                          r"Corp\.|Company|plc|AG|GmbH|S\.A\.|N\.V\.))", body or "")
            return "FR_PRIORITY_REVIEW_VOUCHER", [m.group(1).strip()] if m else []
        return None, []
    if agency in ("federal-energy-regulatory-commission", "nuclear-regulatory-commission") and ";" in title:
        head = title.split(";")[0].strip()
        head = re.split(r"\s+d/b/a\s+", head)[0].strip()
        names = [x.strip() for x in re.split(r",\s+(?=[A-Z])|\s+and\s+(?=[A-Z])", head) if COMPANY.search(x)]
        if names:
            return ("FR_ENERGY_REGULATORY_FILING" if agency.startswith("federal-energy")
                    else "FR_NUCLEAR_LICENSE_ACTION"), names
    return None, []


def load_links(path: Path | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Exact-name index of reviewed links, and of reviewed exclusions."""
    path = path or ROOT / "data" / "issuer_links.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, dict[str, Any]] = {}
    for link in table.get("links", []):
        for name in link.get("names", []):
            index[norm(name)] = link
    aliases = json.loads((ROOT / "data" / "fda_sponsor_aliases.json").read_text(encoding="utf-8"))
    for ticker, names in (aliases.get("aliases") or {}).items():
        for name in names:
            index.setdefault(norm(name), {"ticker": ticker, "legal_entity": name, "relation": "REVIEWED_FDA_SPONSOR_ALIAS",
                                          "evidence": "data/fda_sponsor_aliases.json (reviewed openFDA sponsor table)"})
    excluded = {norm(n): x for x in table.get("excluded", []) for n in x.get("names", [])}
    return index, excluded


def classify(doc: dict[str, Any], index: dict, excluded: dict, body: str | None = None) -> dict[str, Any]:
    kind, names = entities(doc, body)
    base = {"document_number": doc.get("document_number"), "date": doc.get("publication_date"),
            "agency": AGENCY_AR.get(doc.get("agency"), doc.get("agency")), "type": doc.get("type"),
            "title": str(doc.get("title") or "")[:300], "source_url": doc.get("html_url")}
    if not kind:
        return {**base, "status": "GENERAL"}
    label, importance, group = KINDS[kind]
    links, unmatched = [], []
    for name in names:
        hit = index.get(norm(name))
        if hit:
            links.append({"name": name, **{k: hit[k] for k in ("ticker", "legal_entity", "relation", "evidence")
                                           if k in hit}, "listed_company": hit.get("listed_company")})
        else:
            ex = excluded.get(norm(name))
            unmatched.append({"name": name, "reason": ex["reason"] if ex else "NOT_IN_REVIEWED_TABLE"})
    return {**base, "status": "LINKED" if links else "COMPANY_UNLINKED", "kind": kind, "label_ar": label,
            "importance": importance, "group": group, "companies": names, "links": links, "unmatched": unmatched}


def fetch_documents(session: Any, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = (now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    docs, counts = [], {}
    for agency in AGENCIES:
        got = 0
        for page in range(1, MAX_PAGES + 1):
            time.sleep(0.5)
            r = session.get(API, timeout=30, headers=UA, params={
                "per_page": 100, "page": page, "order": "newest", "conditions[agencies][]": agency,
                "conditions[publication_date][gte]": start,
                "fields[]": ["title", "type", "abstract", "document_number", "publication_date", "html_url",
                             "raw_text_url"]})
            r.raise_for_status()
            d = r.json()
            for doc in d.get("results") or []:
                docs.append({**doc, "agency": agency})
            got += len(d.get("results") or [])
            if not d.get("next_page_url"):
                break
        counts[AGENCY_AR[agency]] = got
    return docs, counts


def build(docs: list[dict[str, Any]], counts: dict[str, Any], now: datetime, bodies: dict[str, str] | None = None,
          links_path: Path | None = None) -> dict[str, Any]:
    index, excluded = load_links(links_path)
    seen, rows = set(), []
    for doc in docs:
        number = doc.get("document_number")
        if number in seen or NOISE.search(str(doc.get("title") or "")):
            continue
        seen.add(number)
        rows.append(classify(doc, index, excluded, (bodies or {}).get(number)))
    linked = [r for r in rows if r["status"] == "LINKED"]
    unlinked = [r for r in rows if r["status"] == "COMPANY_UNLINKED"]
    general = [r for r in rows if r["status"] == "GENERAL"]
    by_kind: dict[str, int] = {}
    for r in linked + unlinked:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "source": "Federal Register API (federalregister.gov), U.S. government publication",
        "rights": "U.S. government works are not subject to copyright (17 U.S.C. 105); no API key",
        "documents_by_agency": counts,
        "counts": {"after_noise_filter": len(rows), "linked": len(linked), "company_unlinked": len(unlinked),
                   "general": len(general), "by_kind": by_kind},
        "link_policy": ("exact normalised name in data/issuer_links.json or data/fda_sponsor_aliases.json; "
                        "no similarity matching; joint ventures, partly owned and private companies excluded"),
        "linked": linked,
        "company_unlinked": unlinked,
        "general": general[:80],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        docs, counts = fetch_documents(requests, now)
        bodies = {}
        for doc in docs:
            if str(doc.get("title") or "").startswith("Issuance of Priority Review Voucher") and doc.get("raw_text_url"):
                time.sleep(0.5)
                r = requests.get(doc["raw_text_url"], timeout=30, headers=UA)
                if r.ok:
                    bodies[doc["document_number"]] = re.sub(r"\s+", " ", r.text)
        report = build(docs, counts, now, bodies)
    except (requests.RequestException, ValueError) as exc:
        print(json.dumps({"status": "UNAVAILABLE_KEPT_PREVIOUS", "error": f"{type(exc).__name__}: {exc}"[:200]}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"documents": counts, **report["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
