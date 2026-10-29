"""One-time probe of the USAspending API (U.S. Treasury; federal data, no key): robots.txt,
one transaction search for a known contractor, and one award detail. Prints field names and
one sample row; nothing is stored."""
from __future__ import annotations

import json
import time
import urllib.robotparser
from datetime import date, timedelta

import requests

UA = "GHAZI-RADAR-usaspending-probe/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"
API = "https://api.usaspending.gov/api/v2/"


def main() -> int:
    r = requests.get("https://api.usaspending.gov/robots.txt", timeout=20, headers={"User-Agent": UA})
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    print("ROBOTS", r.status_code, "allowed:", rp.can_fetch(UA, API + "search/spending_by_transaction/"))
    for page in ("https://www.usaspending.gov/about", "https://www.usaspending.gov/robots.txt"):
        x = requests.get(page, timeout=20, headers={"User-Agent": UA})
        print("PAGE", page, x.status_code, x.text[:300].replace("\n", " "))
    end = date.today()
    body = {"filters": {"award_type_codes": ["A", "B", "C", "D"],
                        "time_period": [{"start_date": (end - timedelta(days=14)).isoformat(), "end_date": end.isoformat()}],
                        "recipient_search_text": ["The Boeing Company"]},
            "fields": ["Award ID", "Mod", "Recipient Name", "Action Date", "Transaction Amount", "Awarding Agency",
                       "Awarding Sub Agency", "Award Type", "Transaction Description", "Recipient UEI",
                       "internal_id", "generated_internal_id"],
            "sort": "Transaction Amount", "order": "desc", "limit": 5, "page": 1}
    time.sleep(1)
    t = requests.post(API + "search/spending_by_transaction/", json=body, timeout=40, headers={"User-Agent": UA})
    print("TXN", t.status_code, t.text[:1500])
    try:
        first = (t.json().get("results") or [{}])[0]
    except ValueError:
        first = {}
    gid = first.get("generated_internal_id")
    if gid:
        time.sleep(1)
        a = requests.get(API + f"awards/{gid}/", timeout=40, headers={"User-Agent": UA})
        d = a.json() if a.status_code == 200 else {}
        print("AWARD", a.status_code, "keys:", sorted(d)[:80])
        print("AWARD_SAMPLE", json.dumps({k: d.get(k) for k in ("piid", "total_obligation", "base_and_all_options_value",
                                                                 "base_exercised_options_val", "total_outlay", "date_signed",
                                                                 "period_of_performance")}, default=str)[:800])
        print("RECIPIENT", json.dumps(d.get("recipient"), default=str)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
