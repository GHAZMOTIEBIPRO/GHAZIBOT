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


def _bars_payload(start, n, step_minutes, base=100.0):
    from datetime import timedelta
    rows = []
    for i in range(n):
        t = start + timedelta(minutes=step_minutes * i)
        price = base + i * 0.01
        rows.append({"t": t.isoformat().replace("+00:00", "Z"), "o": price, "h": price + 0.2, "l": price - 0.2,
                     "c": price + 0.05, "v": 1000})
    return {"bars": rows, "next_page_token": None}


def test_private_plans_need_policy_and_keys_and_build_intraday_frames(monkeypatch):
    from datetime import timedelta
    calls = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Session:
        def get(self, url, params=None, headers=None, timeout=None):
            calls.append(params)
            start, end = datetime.fromisoformat(params["start"]), datetime.fromisoformat(params["end"])
            if params["timeframe"] == "1Day":
                first = start.replace(hour=4, minute=0)
                return Response(_bars_payload(first, int((end - first).total_seconds() // 86400) + 1, 24 * 60))
            return Response(_bars_payload(start, int((end - start).total_seconds() // 300), 5))

    now = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)  # Monday 14:00 New York
    facts = bdp.calendar_facts(now)
    denied = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "false"}
    assert bdp.private_plans(facts, now, session=Session(), env=denied)["reason"] == "DATA_USE_PERMISSION_REQUIRED"
    no_keys = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true"}
    assert bdp.private_plans(facts, now, session=Session(), env=no_keys)["reason"] == "ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
    assert calls == []  # neither denial touched the provider
    ok = {**denied, "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true"}
    result = bdp.private_plans(facts, now, session=Session(), env=ok)
    assert result["enabled"] is True and len(calls) == 2 * len(bdp.PLAN_SYMBOLS)
    # nothing newer than now - 16 minutes is ever requested
    assert all(datetime.fromisoformat(c["end"]) <= now - timedelta(minutes=16) for c in calls)
    # completed history uses the consolidated tape (allowed on Basic when 15+ minutes old)
    assert {c["feed"] for c in calls} == {"sip"}
    plan = result["plans"]["SPY"]
    assert plan["available"] is True
    assert {"daily", "weekly", "4h", "1h", "15m", "5m"} <= set(plan["frames_available"])
    # the 4H bucket in progress (13:30-16:00 today) is not used
    assert plan["frames"]["4h"]["last_bar_end"] <= "2026-10-26T17:30:00+00:00"
    assert all(level["source"] == "alpaca_sip" and level["bar"] for level in plan["levels"])
    assert result["fetch_status"]["SPY"]["feeds"] == ["sip"]
    # both series passed the quality checks; the in-progress session's daily bar is not completed
    qc = plan["quality_checks"]
    assert qc["daily"]["status"] == "OK" and qc["5m"]["status"] == "OK" and "clean" not in qc["daily"]
    assert qc["daily"]["forming"] >= 1 and qc["daily"]["adjustment"] == "split" and qc["daily"]["feed"] == "sip"
    # the private message is the cards' template text; options failing does not remove the stock reading
    result["cards"] = bdp.cards_for(result, None, now, "SOURCE_TERMS_BLOCKED")
    spy = result["cards"]["SPY"]
    assert spy["asset_type"] == "ETF" and spy["data_quality"]["daily"]["status"] == "OK"
    assert any(m["item"] == "options" for m in spy["missing"])
    msg = bdp.private_message(result, facts)
    assert "SPY (الشريط المجمع SIP" in msg and "ليس احتمالًا" in msg and "بلا احتمال نجاح" in msg
    # a provider whose history stops weeks ago yields no plan, not an old one
    stale = dict(result["plans"]["SPY"])
    old = bdp.dp.plan_for_symbol("OLD", [{"date": "2026-09-04", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
                                         {"date": "2026-09-05", "open": 1, "high": 2, "low": 0.5, "close": 1.5}],
                                 last_closed_session="2026-10-23", last_closed_week_end="2026-10-23",
                                 provider={"name": "alpaca_iex"})
    assert old["available"] is False and old["reason"].startswith("stale") and stale["available"] is True
    sheet = bdp.build(now, None, None, None, result)
    assert sheet["readiness"]["multi_timeframe"] == {"public": "UNAVAILABLE", "private_owner": "FULL",
                                                     "frames_private": sorted(bdp.FRAMES)}
    assert sheet["readiness"]["price_levels"] == {"public": "NOT_COMPUTED", "private_owner": "COMPUTED"}
    assert sheet["title_ar"] == "موجز الجلسة والمحركات"  # no public frames: not a technical plan
    assert sheet["public_price_plans"] == {} and '"close":' not in json.dumps(sheet)


def test_sheet_without_any_frames_is_a_session_brief():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    sheet = bdp.build(now, {"watchlist": []}, {"treasury_curve": {"curve_date": "2026-10-23"}}, None,
                      {"enabled": False, "reason": "DATA_USE_PERMISSION_REQUIRED", "plans": {}})
    assert sheet["title_ar"] == "موجز الجلسة والمحركات"
    assert sheet["readiness"]["session_and_catalysts"] == "AVAILABLE"
    assert sheet["readiness"]["multi_timeframe"]["private_owner"] == "UNAVAILABLE"
    assert sheet["readiness"]["price_levels"]["private_owner"] == "NOT_COMPUTED"


def test_workflow_publishes_sheet_and_morning_copy_but_never_private_output():
    text = Path(".github/workflows/daily-plan.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    publish = next(s for s in wf["jobs"]["daily-plan"]["steps"] if s.get("name", "").startswith("Publish"))
    assert "runtime/public/data/daily_plan.json" in publish["run"] and "state/daily_plan" in publish["run"]
    assert "private_plan" not in publish["run"] and "--private-output" in text


def test_analysis_funnel_separates_known_news_fetched_analysed_and_qualified():
    nasdaq = {"rows": [["AAPL", "Apple"], ["SOUN", "SoundHound"], ["QQQ", "Invesco"]]}
    directory = {"symbols": [{"symbol": "AAPL"}, {"symbol": "XOM"}]}
    watch = {"events": [{"symbol": "AAPL"}, {"symbol": "AAPL"}, {"symbol": "IONS"}]}
    blocked = {"enabled": False, "reason": "DATA_USE_PERMISSION_REQUIRED", "plans": {}}
    f = bdp.funnel(nasdaq, directory, watch, blocked)
    assert f["known_symbols"]["count"] == 4 and f["known_symbols"]["nasdaq_listed"] == 3
    assert f["with_official_news"]["count"] == 2
    assert f["bars_fetched"] == {**f["bars_fetched"], "count": 0, "attempted": 0, "status": "DATA_USE_PERMISSION_REQUIRED"}
    assert f["analysed"]["count"] == 0 and f["qualified"]["count"] is None
    ran = {"enabled": True, "reason": "OWNER_AUTHORIZED_INTERNAL_USE",
           "fetch_status": {"SPY": {"daily": "OK"}, "AAPL": {"daily": "HTTP_403"}},
           "plans": {"SPY": {"available": True}, "AAPL": {"available": False}}}
    g = bdp.funnel(nasdaq, directory, watch, ran)
    assert (g["bars_fetched"]["count"], g["bars_fetched"]["attempted"], g["analysed"]["count"]) == (1, 2, 1)
    assert "SPY" not in json.dumps(g)            # counts only in the public sheet


def test_private_volume_context_never_treats_yesterdays_intraday_as_todays_breakout():
    from datetime import timedelta
    now = datetime(2026, 10, 30, 15, 30, tzinfo=timezone.utc)
    prior = now - timedelta(days=1)
    daily = {"status": "OK", "clean": [
        {"t": prior, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 900.0},
    ]}
    minute = {"status": "OK", "clean": [{"t": prior}]}
    m15 = {"15m": [{"start": prior.isoformat(), "minutes": 15, "bars_5m": 3,
                      "partial": False, "open": 100, "high": 101, "low": 99,
                      "close": 100, "volume": 900}]}
    result = bdp._private_volume_context(daily, minute, m15, now)
    assert result["status"] == "NO_ACTIVE_INTRADAY_SESSION"
    assert result["inference_only"] is True
    minute["status"] = "DATA_ERROR"
    assert bdp._private_volume_context(daily, minute, m15, now)["status"] == "QUALITY_GATE_BLOCKED"
