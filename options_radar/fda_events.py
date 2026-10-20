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
  project's own company list, by normalised legal name; an event without a
  confident match keeps ticker = null rather than a guess.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

SCHEMA = "ghazi.fda_events.v1"
LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|ltd|limited|plc|llc|lp|sa|ag|nv|se|holdings?|"
    r"group|the|usa|us|pharmaceuticals?|pharma|therapeutics|biosciences?|laboratories|labs)\b")


def normalise(name: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower().replace("&", " and "))
    return re.sub(r"\s+", " ", LEGAL_SUFFIXES.sub(" ", text)).strip()


def build_name_index(aliases: dict[str, str]) -> dict[str, str]:
    """normalised company name -> ticker; names that collide are dropped."""
    index: dict[str, str] = {}
    collisions: set[str] = set()
    for ticker, name in aliases.items():
        key = normalise(name)
        if len(key) < 3:
            continue
        if key in index and index[key] != ticker:
            collisions.add(key)
        index[key] = ticker
    for key in collisions:
        index.pop(key, None)
    return index


def match_ticker(name: Any, index: dict[str, str]) -> tuple[str | None, str]:
    key = normalise(name)
    if not key:
        return None, "no_name"
    if key in index:
        return index[key], "exact_normalised_name"
    return None, "unmatched"


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
            events[key] = {
                "event_id": key,
                "event_type": "APPROVAL_ORIGINAL" if original else "APPROVAL_SUPPLEMENT",
                "date": when,
                "sponsor": str(app.get("sponsor_name") or "")[:120],
                "products": brands[:5],
                "application_number": number,
                "submission_class": klass[:80] or None,
                "review_priority": sub.get("review_priority"),
                "ticker": ticker,
                "match_method": method,
                # Importance describes the regulatory event, not a price move.
                "importance": "HIGH" if original else "MEDIUM" if efficacy else "LOW",
                "importance_reason": ("original application approved" if original else
                                      "efficacy supplement approved" if efficacy else "other supplement approved"),
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
            "recalls": len(recalls),
            "class_i_recalls": sum(e.get("classification") == "Class I" for e in recalls),
            "matched_to_ticker": len(matched),
        },
        "errors": errors or {},
        "source": "openFDA (api.fda.gov): drugsfda and drug enforcement endpoints",
        "rights": "CC0 public domain per open.fda.gov/terms (rights matrix run 39478127523)",
        "notes_ar": [
            "الموافقات والسحوبات وقائع تنظيمية رسمية مؤرخة؛ لا تعني اتجاهًا للسعر ولا يُستنتج منها رد فعل السوق.",
            "ربط الشركة بالرمز يتم فقط بمطابقة الاسم القانوني مع قائمة الشركات؛ عند عدم اليقين يبقى الرمز فارغًا.",
            "تاريخ الحدث هو تاريخ القرار أو التقرير لدى FDA، وقد يُنشر في openFDA بعده بأيام.",
        ],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }
