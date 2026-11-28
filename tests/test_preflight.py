"""Session preflight: rights apart from keys, private chat without sending, no secret in the output."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts import preflight as pf

NOW = datetime(2026, 11, 28, 9, 0, tzinfo=timezone.utc)  # Saturday


class FakeHTTP:
    def __init__(self, codes):
        self.codes, self.calls = codes, []

    def get(self, url, **kw):
        self.calls.append(url)
        code = next((c for k, c in self.codes.items() if k in url), 200)
        body = ({"timestamp": datetime.now(timezone.utc).isoformat()} if "clock" in url else
                {"SPY": {}} if "stocks/snapshots" in url else {"bars": {"SPY": [{}]}} if "stocks/bars" in url else
                {"snapshots": {"X": {}}} if "options" in url else {})
        return SimpleNamespace(status_code=code, json=lambda: body, text="<feed>" if "sec.gov" in url else "")


ENV = {"ALPACA_API_KEY": "kid", "ALPACA_SECRET_KEY": "ksecret", "TELEGRAM_BOT_TOKEN": "123:tok",
       "TELEGRAM_OWNER_CHAT_ID": "4242", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
       "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}


def test_monday_schedule_in_new_york_and_riyadh():
    s = pf.schedule(NOW)
    assert s["session"] == "2026-11-30" and not s["early_close"]
    assert s["EARLY"] == "Mon 08:30 NY / Mon 16:30 RUH" and s["open"] == "Mon 09:30 NY / Mon 17:30 RUH"
    assert s["opening_range_15m_complete_sip"] == "Mon 10:01 NY / Mon 18:01 RUH"
    assert s["close"] == "Mon 16:00 NY / Tue 00:00 RUH"


def test_engines_are_judged_separately_and_full_ready_needs_everything(tmp_path):
    http = FakeHTTP({})
    env = {**ENV, "GITHUB_TOKEN": "gh", "GITHUB_REPOSITORY": "o/r"}
    c = pf.checks(env, NOW, state=tmp_path, get_chat=lambda chat: {"type": "private"}, http=http)
    e = pf.engines(c)
    assert e["premarket_reports"]["status"] == "READY" and e["options_hunter"]["status"] == "READY"
    assert e["sec_news"]["status"] == "BLOCKED" and e["smallcaps"]["status"] == "DEGRADED"  # SEC off
    assert e["iex_stream"]["status"] == "DEGRADED"  # the stream connection is only proven live
    assert not all(v["status"] == "READY" for v in e.values())  # FULL_READY false
    assert not any("sec.gov" in u for u in http.calls)  # no SEC request without a real User-Agent
    text = json.dumps(c)
    assert "ksecret" not in text and "123:tok" not in text and "4242" not in text


def test_bad_content_group_chat_missing_attestation_block_the_right_engines(tmp_path):
    env = {**ENV, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "false", "SEC_USER_AGENT": "GhaziRadar owner@example.com"}
    http = FakeHTTP({"options": 403})
    c = pf.checks(env, NOW, state=tmp_path, get_chat=lambda chat: {"type": "group"}, http=http)
    e = pf.engines(c)
    assert e["premarket_reports"]["status"] == "BLOCKED"
    assert any("DESTINATION_NOT_PRIVATE" in x for x in e["premarket_reports"]["reasons"])
    assert any("not attested" in x for x in e["premarket_reports"]["reasons"])
    assert c["alpaca"]["indicative_options"] == 403 and c["alpaca"]["iex_snapshot"] == 200
    assert pf._valid(200, SimpleNamespace(json=dict), lambda b: "SPY" in b) == "BAD_CONTENT"  # 200 is not enough
    assert c["rights"]["alpaca_iex.telegram_private"] == "NOT_ATTESTED" and c["rights"]["alpaca_iex.fetch"] == "ALLOWED"


def test_outbox_lists_unconfirmed_items_for_manual_review(tmp_path):
    day = tmp_path / "daily_plan" / "2026-11-27"
    day.mkdir(parents=True)
    (day / "report_EARLY.json").write_text(json.dumps({"items": {"a": {"status": "UNCONFIRMED"},
                                                                 "b": {"status": "DELIVERED"}}}))
    assert pf._unconfirmed(tmp_path) == {"2026-11-27": 1}
