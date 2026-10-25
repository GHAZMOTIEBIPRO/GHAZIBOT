"""Pre-open sheet: XNYS calendar facts, recent catalysts, private mode never published."""
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts import build_daily_plan as bdp


def test_calendar_handles_weekend_dst_and_early_close():
    sunday = bdp.calendar_facts(datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
    assert sunday["today_is_session"] is False and sunday["last_closed_session"] == "2026-10-23"
    nxt = sunday["next_session"]
    assert nxt["date"] == "2026-10-26" and nxt["open_new_york"] == "09:30" and nxt["open_riyadh"] == "16:30"
    # After US DST ends (2026-11-01) the Riyadh open moves an hour later.
    after_dst = bdp.calendar_facts(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))["today"]
    assert after_dst["open_riyadh"] == "17:30" and after_dst["utc_offset_new_york"] == "-0500"
    # Day after Thanksgiving: early close at 13:00 New York.
    friday = bdp.calendar_facts(datetime(2026, 11, 27, 12, tzinfo=timezone.utc))["today"]
    assert friday["early_close"] is True and friday["close_new_york"] == "13:00"
    # Mid-session the current day is not a closed session yet.
    mid = bdp.calendar_facts(datetime(2026, 10, 26, 16, tzinfo=timezone.utc))
    assert mid["last_closed_session"] == "2026-10-23" and mid["last_closed_week_end"] == "2026-10-23"


def test_sheet_lists_only_recent_catalyst_events_and_no_prices(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    watch = {"watchlist": [
        {"symbol": "OLDY", "latest_date": "2026-10-23", "catalyst_score": 50,
         "catalysts": [{"kind": "FDA_APPROVAL", "date": "2026-09-25"}, {"kind": "FDA_SUPPLEMENT", "date": "2026-10-23"}]},
        {"symbol": "STALE", "latest_date": "2026-10-01", "catalysts": [{"kind": "FDA_APPROVAL", "date": "2026-10-01"}]}]}
    private = bdp.private_plans(bdp.calendar_facts(now), now)
    assert private["enabled"] is False and private["reason"] == "DATA_USE_PERMISSION_REQUIRED"
    sheet = bdp.build(now, watch, None, None, private)
    assert [(c["symbol"], c["kind"]) for c in sheet["catalysts"]] == [("OLDY", "FDA_SUPPLEMENT")]
    assert all(f["public"] == "UNAVAILABLE" for f in sheet["frames"].values())
    assert sheet["public_price_plans"] == {} and sheet["private_mode"]["published"] is False
    text = json.dumps(sheet)
    assert '"close":' not in text and '"open":' not in text


def test_private_plans_use_alpaca_only_with_keys_and_owner_authorization(monkeypatch):
    calls = []

    class Response:
        status_code, content = 200, b"{}"

        def json(self):
            return {"bars": []}

    class Session:
        def get(self, url, params=None, headers=None, timeout=None):
            calls.append(url)
            return Response()

    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    facts = bdp.calendar_facts(now)
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "false")
    assert bdp.private_plans(facts, now, session=Session())["enabled"] is False and calls == []
    monkeypatch.setenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "true")
    result = bdp.private_plans(facts, now, session=Session())
    assert result["enabled"] is True and len(calls) == 3 * len(bdp.PLAN_SYMBOLS)
    assert all(not p["available"] for p in result["plans"].values())  # empty fixture responses


def test_workflow_publishes_sheet_and_morning_copy_but_never_private_output():
    text = Path(".github/workflows/daily-plan.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    publish = next(s for s in wf["jobs"]["daily-plan"]["steps"] if s.get("name", "").startswith("Publish"))
    assert "runtime/public/data/daily_plan.json" in publish["run"] and "state/daily_plan" in publish["run"]
    assert "private_plan" not in publish["run"] and "--private-output" in text
