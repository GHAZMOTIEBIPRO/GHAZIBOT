"""Official FDA events from openFDA: drug approvals and drug recalls.

openFDA publishes FDA data as CC0 public domain ("You can copy, modify,
distribute, and perform the work, even for commercial purposes, all
without asking permission" - open.fda.gov/terms, rights matrix run
39478127523), so the events can be stored and shown publicly. Standard
library only.

What the events are and are not:
- An approval (submission_status AP) or a recall is an official, dated
  regulatory fact. It is not a price direction, and how the market reacts
  is not inferred here.
- The sponsor or recalling firm is matched to a ticker only through the
  project's own company list, by normalised legal name, or through the
  reviewed sponsor spellings in data/fda_sponsor_aliases.json; an event
  without a confident match keeps ticker = null rather than a guess.
- Importance ranks the regulatory event: an original NDA/BLA approval of a
  new molecular entity or new active ingredient (FDA Type 1/2) is HIGH,
  another original NDA/BLA (new formulation, new manufacturer, ...) is
  MEDIUM, and an original ANDA (a generic copy) is LOW.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

SCHEMA = "ghazi.fda_events.v1"
LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|ltd|limited|plc|llc|lp|sa|ag|nv|se|holdings?|"
    r"group|the|usa|us|pharmaceuticals?|pharma|pharms?|therapeutics|biosciences?|laboratories|labs)\b")
APPLICATION_KIND = re.compile(r"^(ANDA|NDA|BLA)")


def normalise(name: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower().replace("&", " and "))
    return re.sub(r"\s+", " ", LEGAL_SUFFIXES.sub(" ", text)).strip()


def build_name_index(aliases: dict[str, str],
                     sponsors: dict[str, list[str]] | None = None) -> dict[str, tuple[str, str]]:
    """normalised name -> (ticker, method); names that map to two tickers are dropped."""
    entries = [(name, ticker, "exact_normalised_name") for ticker, name in aliases.items()]
    entries += [(name, ticker, "reviewed_sponsor_alias")
                for ticker, names in (sponsors or {}).items() for name in names]
    index: dict[str, tuple[str, str]] = {}
    collisions: set[str] = set()
    for name, ticker, method in entries:
        key = normalise(name)
        if len(key) < 3:
            continue
        if key in index and index[key][0] != ticker:
            collisions.add(key)
        index[key] = (ticker, method)
    for key in collisions:
        index.pop(key, None)
    return index


def match_ticker(name: Any, index: dict[str, tuple[str, str]]) -> tuple[str | None, str]:
    key = normalise(name)
    if not key:
        return None, "no_name"
    if key in index:
        return index[key]
    return None, "unmatched"


def _approval_importance(original: bool, kind: str | None, efficacy: bool, klass: str = "") -> tuple[str, str]:
    # FDA chemical type: Type 1 = new molecular entity, Type 2 = new active
    # ingredient. Other types (new formulation, new manufacturer, previously
    # marketed without an NDA, e.g. medical gases) are not a new medicine.
    if original and kind in {"NDA", "BLA"}:
        if re.match(r"type [12]\b", klass.strip().lower()):
            return "HIGH", f"original {kind} approved: {klass[:60]}"
        return "MEDIUM", f"original {kind} approved: {klass[:60] or 'type not stated'} (not a new molecule)"
    if original and kind == "ANDA":
        return "LOW", "original ANDA approved (generic copy)"
    if original:
        return "LOW", "original application approved (type not stated)"
    if efficacy:
        return "MEDIUM", "efficacy supplement approved"
    return "LOW", "other supplement approved"


def _date(value: Any) -> str | None:
    try:
        return datetime.strptime(str(value), "%Y%m%d").date().isoformat()  # noqa: DTZ007 - calendar date
    except ValueError:
        return None


def approval_events(results: list[dict[str, Any]], index: dict[str, str], start: date, end: date) -> list[dict]:
    events: dict[str, dict] = {}
    for app in results:
        if not isinstance(app, dict):
            continue
        number = str(app.get("application_number") or "")
        kind_match = APPLICATION_KIND.match(number)
        application_kind = kind_match.group(1) if kind_match else None
        products = app.get("products") if isinstance(app.get("products"), list) else []
        brands = sorted({str(p.get("brand_name") or "").strip() for p in products if isinstance(p, dict)} - {""})
        ticker, method = match_ticker(app.get("sponsor_name"), index)
        for sub in app.get("submissions") or []:
            if not isinstance(sub, dict) or sub.get("submission_status") != "AP":
                continue
            when = _date(sub.get("submission_status_date"))
            if when is None or not (start.isoformat() <= when <= end.isoformat()):
                continue
            kind = str(sub.get("submission_type") or "")
            klass = str(sub.get("submission_class_code_description") or sub.get("submission_class_code") or "")
            original = kind == "ORIG"
            efficacy = "efficacy" in klass.lower()
            key = f"{number}-{kind}-{sub.get('submission_number')}"
            digits = re.sub(r"\D", "", number)
            importance, reason = _approval_importance(original, application_kind, efficacy, klass)
            events[key] = {
                "event_id": key,
                "event_type": "APPROVAL_ORIGINAL" if original else "APPROVAL_SUPPLEMENT",
                "date": when,
                "sponsor": str(app.get("sponsor_name") or "")[:120],
                "products": brands[:5],
                "application_number": number,
                "application_kind": application_kind,
                "submission_class": klass[:80] or None,
                "review_priority": sub.get("review_priority"),
                "ticker": ticker,
                "match_method": method,
                # Importance describes the regulatory event, not a price move.
                "importance": importance,
                "importance_reason": reason,
                "official_url": (f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={digits}"
                                 if digits else None),
            }
    return sorted(events.values(), key=lambda e: (e["date"], e["event_id"]), reverse=True)


def recall_events(results: list[dict[str, Any]], index: dict[str, str]) -> list[dict]:
    events: dict[str, dict] = {}
    for row in results:
        if not isinstance(row, dict) or not row.get("recall_number"):
            continue
        ticker, method = match_ticker(row.get("recalling_firm"), index)
        classification = str(row.get("classification") or "")
        events[str(row["recall_number"])] = {
            "event_id": str(row["recall_number"]),
            "event_type": "RECALL",
            "date": _date(row.get("report_date")),
            "initiated": _date(row.get("recall_initiation_date")),
            "firm": str(row.get("recalling_firm") or "")[:120],
            "classification": classification or None,
            "status": row.get("status"),
            "product": str(row.get("product_description") or "")[:200],
            "reason": str(row.get("reason_for_recall") or "")[:240],
            "ticker": ticker,
            "match_method": method,
            "importance": "HIGH" if classification == "Class I" else "MEDIUM" if classification == "Class II" else "LOW",
            "importance_reason": f"{classification or 'unclassified'} recall (FDA classification)",
        }
    return sorted(events.values(), key=lambda e: (e["date"] or "", e["event_id"]), reverse=True)


def build(approvals: list[dict], recalls: list[dict], *, generated_at: str, start: date, end: date,
          errors: dict[str, str] | None = None) -> dict[str, Any]:
    matched = [e for e in approvals + recalls if e.get("ticker")]
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "approvals": approvals,
        "recalls": recalls,
        "counts": {
            "approvals": len(approvals),
            "original_approvals": sum(e["event_type"] == "APPROVAL_ORIGINAL" for e in approvals),
            "new_drug_or_biologic_approvals": sum(e["event_type"] == "APPROVAL_ORIGINAL" and
                                                  e.get("application_kind") in {"NDA", "BLA"} for e in approvals),
            "new_molecule_approvals": sum(e["event_type"] == "APPROVAL_ORIGINAL" and e["importance"] == "HIGH"
                                          for e in approvals),
            "recalls": len(recalls),
            "class_i_recalls": sum(e.get("classification") == "Class I" for e in recalls),
            "matched_to_ticker": len(matched),
        },
        "errors": errors or {},
        "source": "openFDA (api.fda.gov): drugsfda and drug enforcement endpoints",
        "rights": "CC0 public domain per open.fda.gov/terms (rights matrix run 39478127523)",
        "notes_ar": [
            "الموافقات والسحوبات وقائع تنظيمية رسمية مؤرخة؛ لا تعني اتجاهًا للسعر ولا يُستنتج منها رد فعل السوق.",
            "ربط الشركة بالرمز يتم فقط بمطابقة الاسم القانوني مع قائمة الشركات أو بأسماء رعاة FDA المراجَعة؛ عند عدم اليقين يبقى الرمز فارغًا.",
            "الأهمية العالية للموافقة الأصلية على جزيء جديد أو مادة فعالة جديدة (FDA Type 1/2)؛ تركيبة أو مصنّع جديد أهمية متوسطة؛ الدواء الجنيس (ANDA) أهمية منخفضة.",
            "تاريخ الحدث هو تاريخ القرار أو التقرير لدى FDA، وقد يُنشر في openFDA بعده بأيام.",
        ],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }
