from __future__ import annotations

from datetime import datetime, timezone

from scripts import build_week_agenda as wa


def test_exchange_closures_and_early_closes_come_from_the_xnys_calendar():
    # Thanksgiving 2026 (Thu 26 Nov) is closed and Fri 27 Nov closes early at 13:00 New York time.
    r = wa.build(None, None, datetime(2026, 11, 23, 15, tzinfo=timezone.utc))
    by_date = {x["date"]: x for x in r["items"] if x["basis"] == "EXCHANGE_CALENDAR"}
    assert by_date["2026-11-26"]["kind"] == "MARKET_CLOSED"
    assert by_date["2026-11-27"]["kind"] == "EARLY_CLOSE" and by_date["2026-11-27"]["time_et"] == "13:00"
    assert not any(x["date"] in ("2026-11-28", "2026-11-29") for x in r["items"])        # weekends are not "holidays"


def test_only_dates_a_source_set_are_listed_inside_the_window():
    cats = {"events": [
        {"symbol": "NVDA", "kind": "IR_SCHEDULE", "date": "2026-10-28", "scheduled_for": "2026-11-03",
         "reason": "11/03/2026 : Example call", "source": "Company IR", "source_url": "https://investor.nvidia.com/e/1"},
        {"symbol": "XOM", "kind": "IR_SCHEDULE", "date": "2026-10-16", "scheduled_for": None, "reason": "no date given"},
        {"symbol": "LATE", "kind": "IR_SCHEDULE", "date": "2026-10-20", "scheduled_for": "2026-12-01", "reason": "far"}]}
    fr = {"linked": [{"title": "Airworthiness Directives; The Boeing Company Airplanes", "label_ar": "توجيه",
                      "effective_on": "2026-11-02", "comments_close_on": None, "source_url": "https://www.federalregister.gov/d/1",
                      "links": [{"ticker": "BA"}], "potential_impact": "NEEDS_IMPACT_ASSESSMENT"}]}
    r = wa.build(cats, fr, datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    assert r["window"] == {"from": "2026-10-29", "to": "2026-11-05", "timezone": "America/New_York"}
    company = [x for x in r["items"] if x["basis"] == "COMPANY_ANNOUNCED"]
    assert [(x["symbol"], x["date"], x["announced_on"]) for x in company] == [("NVDA", "2026-11-03", "2026-10-28")]
    rule = next(x for x in r["items"] if x["kind"] == "RULE_EFFECTIVE")
    assert rule["symbols"] == ["BA"] and rule["date"] == "2026-11-02" and rule["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT"
    assert [x["date"] for x in r["items"]] == sorted(x["date"] for x in r["items"])
