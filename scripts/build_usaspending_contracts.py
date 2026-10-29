"""Federal contract actions for reviewed listed companies (USAspending API, U.S. Treasury; no key).

For each company in data/usaspending_recipients.json: one transaction search (contracts, last
WINDOW_DAYS days, largest MAX_TXN by amount), then each award's detail once, and only actions whose
award's parent recipient UEI is reviewed for that company are kept.

Amounts are kept apart and never added across kinds:
- action_obligation: what this action (a new award or a modification) obligated; negative = deobligation;
- award_total_obligation: everything obligated on the award so far;
- award_ceiling: base and all options, a maximum, not money committed;
- award_total_outlay: what has actually been paid.
A company's window total is the sum of its distinct actions' obligations only. Agencies report with
delays, so an action date can be weeks before it appears. None of this says what an action means for
the company's earnings or share price.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

SCHEMA = "ghazi.usaspending_contracts.v1"
ROOT = Path(__file__).resolve().parents[1]
API = "https://api.usaspending.gov/api/v2/"
UA = {"User-Agent": "GHAZI-RADAR-usaspending/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
WINDOW_DAYS = 10
MAX_TXN = 50
MAX_AWARDS = 20
FIELDS = ["Award ID", "Mod", "Recipient Name", "Action Date", "Transaction Amount", "Awarding Agency",
          "Awarding Sub Agency", "Award Type", "Transaction Description", "Recipient UEI", "internal_id",
          "generated_internal_id"]


def _num(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def actions_for(company: dict[str, Any], txns: list[dict[str, Any]], awards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure: transactions + award details -> kept actions (parent UEI reviewed), deduplicated by transaction id."""
    parents = company["parents"]
    out, seen = [], set()
    for t in txns:
        gid = t.get("generated_internal_id")
        award = awards.get(gid) or {}
        rec = award.get("recipient") or {}
        uei = rec.get("parent_recipient_uei")
        tid = t.get("internal_id")
        if uei not in parents or tid in seen:
            continue
        seen.add(tid)
        out.append({
            "symbol": company["ticker"], "company": company["company"], "action_date": t.get("Action Date"),
            "award_id": t.get("Award ID"), "modification": t.get("Mod"), "transaction_id": tid,
            "recipient": t.get("Recipient Name"), "parent_recipient": rec.get("parent_recipient_name"), "parent_uei": uei,
            "agency": t.get("Awarding Agency"), "sub_agency": t.get("Awarding Sub Agency"), "award_type": t.get("Award Type"),
            "description": str(t.get("Transaction Description") or "")[:200],
            "action_obligation": _num(t.get("Transaction Amount")),
            "award_total_obligation": _num(award.get("total_obligation")),
            "award_ceiling": _num(award.get("base_and_all_options")),
            "award_total_outlay": _num(award.get("total_outlay")),
            "award_url": f"https://www.usaspending.gov/award/{gid}" if gid else None,
            "link_basis": "PARENT_UEI_REVIEWED", "potential_impact": "NEEDS_IMPACT_ASSESSMENT"})
    out.sort(key=lambda a: abs(a["action_obligation"] or 0), reverse=True)
    return out


def fetch_company(company: dict[str, Any], session: Any, start: str, end: str) -> tuple[str, list[dict[str, Any]]]:
    txns: list[dict[str, Any]] = []
    # Largest obligations first, then largest deobligations (negative amounts), so neither end is cut off.
    for order, limit in (("desc", MAX_TXN), ("asc", MAX_TXN // 2)):
        body = {"filters": {"award_type_codes": ["A", "B", "C", "D"], "time_period": [{"start_date": start, "end_date": end}],
                            "recipient_search_text": [company["search"]]},
                "fields": FIELDS, "sort": "Transaction Amount", "order": order, "limit": limit, "page": 1}
        time.sleep(1)
        r = session.post(API + "search/spending_by_transaction/", json=body, timeout=60, headers=UA)
        if r.status_code != 200:
            return f"HTTP_{r.status_code}", []
        txns += r.json().get("results") or []
    awards: dict[str, dict[str, Any]] = {}
    for gid in list(dict.fromkeys(t.get("generated_internal_id") for t in txns if t.get("generated_internal_id")))[:MAX_AWARDS]:
        time.sleep(1)
        a = session.get(API + f"awards/{gid}/", timeout=60, headers=UA)
        if a.status_code == 200:
            awards[gid] = a.json()
    return "OK", actions_for(company, txns, awards)


def build(table: dict[str, Any], fetched: dict[str, tuple[str, list[dict[str, Any]]]], now: datetime,
          previous: dict[str, Any] | None = None) -> dict[str, Any]:
    prev = {c.get("symbol"): c for c in (previous or {}).get("companies", []) if isinstance(c, dict)}
    companies, actions = [], []
    for company in table["companies"]:
        status, got = fetched.get(company["ticker"], ("NOT_FETCHED", []))
        if status != "OK":
            # this company only: keep its last good actions, marked with when they were fetched
            old = prev.get(company["ticker"]) or {}
            got = [a for a in (previous or {}).get("actions", []) if a.get("symbol") == company["ticker"]]
            companies.append({"symbol": company["ticker"], "status": status, "actions": len(got),
                              "last_success_at": old.get("last_success_at"), "kept_previous": bool(got)})
        else:
            net = round(sum(a["action_obligation"] or 0 for a in got), 2)
            companies.append({"symbol": company["ticker"], "status": "OK", "actions": len(got),
                              "window_net_action_obligations": net, "last_success_at": now.isoformat()})
        actions += got
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "window_days": WINDOW_DAYS,
            "source": "USAspending API (api.usaspending.gov), U.S. Department of the Treasury",
            "rights": "U.S. government works are not subject to copyright (17 U.S.C. 105); no API key",
            "amounts_note_ar": ("التزام الإجراء: ما التزمت به الجهة في هذا الإجراء (سالب = إلغاء التزام). إجمالي الالتزام: كل ما التُزم به على العقد حتى الآن. "
                                "السقف: الحد الأعلى مع كل الخيارات وليس مالًا ملتزمًا. المدفوع: ما صُرف فعلًا. لا تُجمع هذه الأرقام معًا، "
                                "وقد تتأخر الجهات في النشر، والرقم لا يعني أثرًا على الأرباح أو السعر."),
            "coverage_note_ar": ("عقود وزارة الدفاع تُنشر عادةً بتأخير نحو 90 يومًا، فنادرًا ما تظهر في نافذة الأيام الأخيرة؛ "
                                 "في تشغيل التحقق 40794573730 جاءت الإجراءات المعروضة من وزارات الأمن الداخلي والنقل وناسا."),
            "companies": companies, "actions": actions,
            "counts": {"companies": len(companies), "companies_ok": sum(c["status"] == "OK" for c in companies),
                       "actions": len(actions)},
            "research_only": True, "decision_authority": False, "execution_authority": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    table = json.loads((ROOT / "data" / "usaspending_recipients.json").read_text(encoding="utf-8"))
    previous = None
    if args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    now = datetime.now(timezone.utc)
    end = now.date()
    start = (end - timedelta(days=WINDOW_DAYS)).isoformat()
    fetched = {}
    for company in table["companies"]:
        try:
            fetched[company["ticker"]] = fetch_company(company, requests, start, end.isoformat())
        except (requests.RequestException, ValueError) as exc:
            fetched[company["ticker"]] = (f"FETCH_ERROR ({type(exc).__name__})", [])
    report = build(table, fetched, now, previous if (previous or {}).get("schema") == SCHEMA else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "companies": [(c["symbol"], c["status"], c["actions"]) for c in report["companies"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
