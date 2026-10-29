"""Probe of the USAspending API (U.S. Treasury; federal data, no key): for each search name, the
parent recipients (name + UEI) of the awards behind its recent contract transactions, so the
reviewed table can link by parent exactly. Prints only; nothing is stored."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, timedelta

import requests

UA = "GHAZI-RADAR-usaspending-probe/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"
API = "https://api.usaspending.gov/api/v2/"
NAMES = {"BA": "The Boeing Company", "LMT": "Lockheed Martin", "RTX": "RTX Corporation", "NOC": "Northrop Grumman",
         "GD": "General Dynamics", "LHX": "L3Harris", "HII": "Huntington Ingalls", "PLTR": "Palantir",
         "LDOS": "Leidos", "BAH": "Booz Allen Hamilton", "GE": "General Electric", "TXT": "Textron"}


def main() -> int:
    end = date.today()
    for ticker, name in NAMES.items():
        body = {"filters": {"award_type_codes": ["A", "B", "C", "D"],
                            "time_period": [{"start_date": (end - timedelta(days=14)).isoformat(), "end_date": end.isoformat()}],
                            "recipient_search_text": [name]},
                "fields": ["Award ID", "Mod", "Recipient Name", "Action Date", "Transaction Amount", "generated_internal_id"],
                "sort": "Transaction Amount", "order": "desc", "limit": 25, "page": 1}
        time.sleep(1)
        t = requests.post(API + "search/spending_by_transaction/", json=body, timeout=40, headers={"User-Agent": UA})
        rows = t.json().get("results", []) if t.status_code == 200 else []
        parents: Counter = Counter()
        for gid in list(dict.fromkeys(r.get("generated_internal_id") for r in rows if r.get("generated_internal_id")))[:8]:
            time.sleep(1)
            a = requests.get(API + f"awards/{gid}/", timeout=40, headers={"User-Agent": UA})
            rec = (a.json() or {}).get("recipient") or {} if a.status_code == 200 else {}
            parents[(rec.get("parent_recipient_name"), rec.get("parent_recipient_uei"))] += 1
        print("PARENTS", json.dumps({"ticker": ticker, "search": name, "http": t.status_code, "transactions": len(rows),
                                     "recipients": sorted({r.get("Recipient Name") for r in rows})[:8],
                                     "parents": [[n, u, c] for (n, u), c in parents.most_common()]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
