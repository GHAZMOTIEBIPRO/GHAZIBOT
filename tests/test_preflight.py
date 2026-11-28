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
        body = {"timestamp": datetime.now(timezone.utc).isoformat()} if "clock" in url else {}
        return SimpleNamespace(status_code=code, json=lambda: body)


ENV = {"ALPACA_API_KEY": "kid", "ALPACA_SECRET_KEY": "ksecret", "TELEGRAM_BOT_TOKEN": "123:tok",
       "TELEGRAM_OWNER_CHAT_ID": "4242", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
       "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}


def test_monday_schedule_in_new_york_and_riyadh():
    s = pf.schedule(NOW)
    assert s["session"] == "2026-11-30" and not s["early_close"]
    assert s["EARLY"] == "Mon 08:30 NY / Mon 16:30 RUH" and s["open"] == "Mon 09:30 NY / Mon 17:30 RUH"
    assert s["opening_range_15m_complete_sip"] == "Mon 10:01 NY / Mon 18:01 RUH"
    assert s["close"] == "Mon 16:00 NY / Tue 00:00 RUH"


def test_ready_without_state_key_is_degraded_not_blocked(tmp_path):
    http = FakeHTTP({})
    c = pf.checks(ENV, NOW, state=tmp_path, get_chat=lambda chat: {"type": "private"}, http=http)
    assert c["private_chat"] == "OK" and c["rights"]["alpaca_iex.telegram_private"] == "ALLOWED"
    assert c["rights"]["alpaca_iex.telegram_public"] == "DENIED"
    b = pf.blockers(c)
    assert all(x.startswith("DEGRADED") for x in b) and any("GHAZI_STATE_HMAC_KEY" in x for x in b)
    assert not any("sec.gov" in u for u in http.calls)  # no SEC request without a real User-Agent
    text = json.dumps(c)
    assert "ksecret" not in text and "123:tok" not in text and "4242" not in text


def test_group_chat_missing_attestation_and_403_block(tmp_path):
    env = {**ENV, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "false", "GHAZI_STATE_HMAC_KEY": "z" * 40,
           "SEC_USER_AGENT": "GhaziRadar owner@example.com"}
    c = pf.checks(env, NOW, state=tmp_path, get_chat=lambda chat: {"type": "group"},
                  http=FakeHTTP({"options": 403, "sec.gov": 403}))
    b = pf.blockers(c)
    assert "CHAT: DESTINATION_NOT_PRIVATE" in b and any(x.startswith("RIGHTS") for x in b)
    assert c["rights"]["alpaca_iex.telegram_private"] == "NOT_ATTESTED" and c["rights"]["alpaca_iex.fetch"] == "ALLOWED"
    assert "ALPACA: indicative_options 403" in b and "DEGRADED: SEC feed 403 (SEC news off)" in b
    assert c["keys"]["state_key_id"] and len(c["keys"]["state_key_id"]) == 8


def test_outbox_lists_unconfirmed_items_for_manual_review(tmp_path):
    day = tmp_path / "daily_plan" / "2026-11-27"
    day.mkdir(parents=True)
    (day / "report_EARLY.json").write_text(json.dumps({"items": {"a": {"status": "UNCONFIRMED"},
                                                                 "b": {"status": "DELIVERED"}}}))
    assert pf._unconfirmed(tmp_path) == {"2026-11-27": 1}
