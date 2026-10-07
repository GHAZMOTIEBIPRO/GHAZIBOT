from datetime import timedelta

from options_radar.contract_guardian import update_contract_guardian
from scripts.send_contract_guardian_updates import _message
from tests.test_guardian_research import NOW, _payload


def test_untimed_option_quote_never_claims_current_return():
    _, state = update_contract_guardian(_payload(), {}, now=NOW)
    later = NOW + timedelta(minutes=15)
    payload = _payload()
    option = payload["expiry_radar"]["tabs"]["all_expirations"]["calls"][0]
    option.pop("quote_timestamp")
    option.update({"updated_at": later.isoformat(), "bid": 0.1, "ask": 0.2})
    _, state = update_contract_guardian(payload, state, now=later)
    tracked = next(iter(state["contracts"].values()))
    assert tracked["data_stale"] is True
    assert tracked["last_mark"] is None
    assert tracked["last_return_pct"] is None
    assert tracked["last_indicative_mark"] == 0.1
    assert "قيمة إرشادية" in _message(tracked)


def test_untimed_underlying_invalidation_is_provisional():
    payload = _payload()
    option = payload["expiry_radar"]["tabs"]["all_expirations"]["calls"][0]
    option["underlying_price"] = 45.0
    _, state = update_contract_guardian(payload, {}, now=NOW)
    tracked = next(iter(state["contracts"].values()))
    assert tracked["stage"] == "INVALIDATED"
    assert tracked["stage_provisional"] is True
    assert tracked["terminal"] is False

    later = NOW + timedelta(minutes=10)
    payload = _payload()
    payload["expiry_radar"]["tabs"]["all_expirations"]["calls"][0]["quote_timestamp"] = later.isoformat()
    _, state = update_contract_guardian(payload, state, now=later)
    tracked = next(iter(state["contracts"].values()))
    assert tracked["terminal"] is False
    assert tracked["stage"] != "INVALIDATED"


def test_elapsed_quote_time_does_not_validate_profit():
    _, state = update_contract_guardian(_payload(), {}, now=NOW)
    later = NOW + timedelta(hours=4)
    payload = _payload()
    option = payload["expiry_radar"]["tabs"]["all_expirations"]["calls"][0]
    option.update({"bid": 10.0, "ask": 10.2})
    report, state = update_contract_guardian(payload, state, now=later)
    tracked = next(iter(state["contracts"].values()))
    assert tracked["data_stale"] is True
    assert tracked["last_return_pct"] is None
    assert tracked["quote_history_count"] == 1
    assert report["unstamped_option_count"] == 1
