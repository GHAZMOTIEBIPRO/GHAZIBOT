from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import build_usaspending_contracts as us

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)
BA = {"ticker": "BA", "company": "The Boeing Company", "search": "The Boeing Company",
      "parents": {"NU2UC8MX6NK1": "THE BOEING COMPANY"}}
TXNS = [
    {"Award ID": "NAS1510000", "Mod": "3258", "Recipient Name": "THE BOEING COMPANY", "Action Date": "2026-10-15",
     "Transaction Amount": 3737534.53, "Awarding Agency": "NASA", "internal_id": 1, "generated_internal_id": "CONT_AWD_A"},
    {"Award ID": "NAS1510000", "Mod": "3259", "Recipient Name": "THE BOEING COMPANY", "Action Date": "2026-10-16",
     "Transaction Amount": -500000.0, "Awarding Agency": "NASA", "internal_id": 2, "generated_internal_id": "CONT_AWD_A"},
    {"Award ID": "15M10426PA3700016", "Mod": "P00001", "Recipient Name": "JEPPESEN FOREFLIGHT, INC.", "Action Date": "2026-10-15",
     "Transaction Amount": 149981.0, "Awarding Agency": "DOJ", "internal_id": 3, "generated_internal_id": "CONT_AWD_J"},
    {"Award ID": "NAS1510000", "Mod": "3258", "Recipient Name": "THE BOEING COMPANY", "Action Date": "2026-10-15",
     "Transaction Amount": 3737534.53, "Awarding Agency": "NASA", "internal_id": 1, "generated_internal_id": "CONT_AWD_A"}]
AWARDS = {"CONT_AWD_A": {"total_obligation": 22657326734.37, "base_and_all_options": None, "total_outlay": 2714678720.61,
                         "recipient": {"parent_recipient_name": "THE BOEING COMPANY", "parent_recipient_uei": "NU2UC8MX6NK1"}},
          "CONT_AWD_J": {"total_obligation": 149981.0, "recipient": {"parent_recipient_name": "THOMA BRAVO",
                                                                     "parent_recipient_uei": "OTHER"}}}


def test_only_the_reviewed_parent_links_and_amount_kinds_stay_apart():
    got = us.actions_for(BA, TXNS, AWARDS)
    # the search name found a former Boeing business too; its parent is not Boeing, so it does not link
    assert {a["recipient"] for a in got} == {"THE BOEING COMPANY"}
    assert [a["transaction_id"] for a in got] == [1, 2]                          # duplicate transaction dropped
    first = got[0]
    assert first["action_obligation"] == 3737534.53 and first["award_total_obligation"] == 22657326734.37
    assert first["award_ceiling"] is None and first["award_total_outlay"] == 2714678720.61
    assert got[1]["action_obligation"] == -500000.0                             # a deobligation stays negative
    assert first["award_url"] == "https://www.usaspending.gov/award/CONT_AWD_A"
    assert first["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT"


def test_window_total_is_actions_only_and_each_company_fails_alone():
    table = {"companies": [BA, {**BA, "ticker": "LMT", "company": "Lockheed Martin", "parents": {"X": "LM"}}]}
    first = us.build(table, {"BA": ("OK", us.actions_for(BA, TXNS, AWARDS)), "LMT": ("OK", [])}, NOW)
    ba = next(c for c in first["companies"] if c["symbol"] == "BA")
    assert ba["window_net_action_obligations"] == round(3737534.53 - 500000.0, 2)      # never ceilings or totals
    later = us.build(table, {"BA": ("HTTP_503", []), "LMT": ("OK", [])}, NOW, first)
    ba2 = next(c for c in later["companies"] if c["symbol"] == "BA")
    assert ba2["status"] == "HTTP_503" and ba2["kept_previous"] and ba2["last_success_at"] == NOW.isoformat()
    assert len([a for a in later["actions"] if a["symbol"] == "BA"]) == 2


def test_reviewed_table_links_by_parent_uei_only():
    table = json.loads((ROOT / "data" / "usaspending_recipients.json").read_text(encoding="utf-8"))
    for c in table["companies"]:
        assert c["parents"] and all(len(u) == 12 and u.isalnum() for u in c["parents"]), c["ticker"]
    assert {x["ticker"] for x in table["not_linked"]} == {"GE", "HII"}
