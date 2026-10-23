"""Bounded ClinicalTrials.gov v2 registry facts; never trial outcome predictions.

Independent adapter, no pytrials code copied. Only a matched INDUSTRY lead
sponsor establishes ticker identity; collaborators and fuzzy matches are ignored.
The output database is offered under ODbL-1.0, with NLM attribution.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("registry_name_index", ROOT / "options_radar/fda_events.py")
_names = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_names)
SCHEMA = "ghazi.clinical_registry_feed.v1"
API = "https://clinicaltrials.gov/api/v2/studies"
ATTRIBUTION = "Courtesy of the U.S. National Library of Medicine"
WINDOW_DAYS = 14


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def study_event(study: Any, index: dict, *, start: date, end: date) -> dict | None:
    if not isinstance(study, dict):
        return None
    protocol = study.get("protocolSection")
    if not isinstance(protocol, dict):
        return None
    identity = protocol.get("identificationModule") or {}
    sponsors = protocol.get("sponsorCollaboratorsModule") or {}
    status = protocol.get("statusModule") or {}
    if not all(isinstance(x, dict) for x in (identity, sponsors, status)):
        return None
    sponsor = sponsors.get("leadSponsor")
    if not isinstance(sponsor, dict) or sponsor.get("class") != "INDUSTRY":
        return None
    symbol, method = _names.match_ticker(sponsor.get("name"), index)
    nct = identity.get("nctId")
    if not symbol or not re.fullmatch(r"NCT[0-9]{8}", str(nct or "")):
        return None
    updated = status.get("lastUpdatePostDateStruct") or {}
    results = status.get("resultsFirstPostDateStruct") or {}
    if not isinstance(updated, dict) or not isinstance(results, dict):
        return None
    updated_day, results_day = _day(updated.get("date")), _day(results.get("date"))
    if updated_day is None or not start <= updated_day <= end:
        return None
    kind, importance = "TRIAL_REGISTRY_UPDATE", "LOW"
    label = "تحديث سجل دراسة؛ لا يثبت نتيجة إيجابية أو سلبية"
    event_day = updated_day
    if (study.get("hasResults") is True and results.get("type") == "ACTUAL"
            and results_day is not None and start <= results_day <= updated_day):
        kind, importance = "TRIAL_RESULTS_POSTED", "MEDIUM"
        label = "نُشرت نتائج في السجل؛ اتجاه النتيجة لم يُقيّم"
        event_day = results_day
    elif status.get("overallStatus") in {"TERMINATED", "SUSPENDED", "WITHDRAWN"}:
        kind, importance = "TRIAL_STATUS_REVIEW", "MEDIUM"
        label = "سجل محدّث يحمل حالة إيقاف/تعليق/سحب؛ تاريخ تغير الحالة وسببه غير مثبتين"
    return {
        "symbol": symbol, "kind": kind, "importance": importance,
        "date": event_day.isoformat(), "registry_updated_date": updated_day.isoformat(),
        "label": label, "reason": str(identity.get("briefTitle") or nct)[:160],
        "source": "ClinicalTrials.gov", "source_url": f"https://clinicaltrials.gov/study/{nct}",
        "match_method": method, "lead_sponsor": str(sponsor.get("name"))[:120],
        "registry_status": str(status.get("overallStatus") or "UNKNOWN")[:50],
        "outcome_direction": "NOT_INFERRED", "official_registry_only": True,
    }


def get_page(params: dict) -> dict:
    request = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={
        "User-Agent": "GHAZI-RADAR registry research (github.com/GHAZMOTIEBIPRO/GHAZIBOT)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("registry response too large")
    return json.loads(raw)


def collect(index: dict, *, now: datetime, fetch: Callable = get_page, max_pages: int = 3) -> dict:
    if now.tzinfo is None:
        raise ValueError("aware time required")
    now = now.astimezone(timezone.utc)
    end, start = now.date(), now.date() - timedelta(days=WINDOW_DAYS)
    params = {"format": "json", "pageSize": 250, "sort": "LastUpdatePostDate:desc",
              "query.term": "AREA[LeadSponsorClass]INDUSTRY AND "
              f"AREA[LastUpdatePostDate]RANGE[{start.isoformat()},{end.isoformat()}]"}
    events: dict[str, dict] = {}
    pages, records, token, error = 0, 0, "", None
    seen_tokens: set[str] = set()
    for _ in range(min(3, max(1, max_pages))):
        try:
            payload = fetch({**params, **({"pageToken": token} if token else {})})
            if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
                raise TypeError("invalid studies schema")
            next_token = payload.get("nextPageToken", "")
            if not isinstance(next_token, str) or len(next_token) > 4096:
                raise ValueError("invalid pagination token")
            pages += 1
            records += len(payload["studies"])
            for study in payload["studies"]:
                event = study_event(study, index, start=start, end=end)
                if event:
                    key = event["source_url"]
                    if key not in events or event["registry_updated_date"] > events[key]["registry_updated_date"]:
                        events[key] = event
            token = next_token
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("repeated pagination token")
            seen_tokens.add(token)
        except (OSError, ValueError, TypeError) as exc:
            error = type(exc).__name__  # never publish raw server text/URLs
            break
    return {
        "schema": SCHEMA, "generated_at": now.isoformat(),
        "status": "UNAVAILABLE" if not pages else "PARTIAL" if error or token else "OK",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "coverage_complete": bool(pages and not error and not token),
        "pages_received": pages, "records_received": records,
        "events": sorted(events.values(), key=lambda x: (x["date"], x["symbol"]), reverse=True),
        "error": error, "source": "ClinicalTrials.gov", "source_url": API,
        "attribution": ATTRIBUTION, "database_license": "ODbL-1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "research_only": True, "decision_authority": False, "execution_authority": False,
        "note_ar": "سجل حكومي بمعلومات يقدمها الرعاة؛ ليس إثبات نجاح علاج أو اتجاه سهم. التغطية محدودة بـ750 سجلًا. لا يمثل تأييدًا من NLM وقد لا يعكس آخر تعديل.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    aliases = json.loads((ROOT / "data/company_aliases.json").read_text())
    sponsors = json.loads((ROOT / "data/fda_sponsor_aliases.json").read_text())["aliases"]
    report = collect(_names.build_name_index(aliases, sponsors), now=datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(args.output)
    print(json.dumps({k: report[k] for k in ("status", "pages_received", "records_received", "error")}))
    print("Matched registry events:", len(report["events"]))
    # An unavailable diagnostic is a valid output; independent FDA/SEC continue.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
