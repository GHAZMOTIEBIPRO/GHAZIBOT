import json
from datetime import datetime, timezone

import pytest

from scripts.preflight_tradier_free_live import _request_json, probe, quote_quality

NOW = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
ENV = {"TRADIER_TOKEN": "secret-sentinel", "TRADIER_BASE_URL": "https://api.tradier.com",
       "TRADIER_INTERNAL_DATA_USE_AUTHORIZED": "true"}


def quote(**kw):
    return {"bid": 123.45, "ask": 124.56, "bid_date": NOW.timestamp() * 1000,
            "ask_date": NOW.timestamp() * 1000, **kw}


def fake(base, path, token, **params):
    if path == "quotes":
        return {"quotes": {"quote": quote(symbol="SPY", type="etf")}}
    if path == "options/expirations":
        return {"expirations": {"date": ["bad", "2026-10-23", "2026-10-22"]}}
    assert path == "options/chains"
    return {"options": {"option": quote(symbol="SPY261023C00600000", type="option",
                                         underlying="SPY", contract_size=100)}}


def test_access_is_not_execution_or_redistribution_and_has_no_prices():
    result = probe(ENV, now=NOW, request=fake)
    assert result["status"] == "ACCESS_VERIFIED"
    assert result["checks"]["option_two_sided_fresh"]
    assert result["ready"] is result["execution_authority"] is result["public_redistribution"] is False
    text = json.dumps(result)
    assert "123.45" not in text and "124.56" not in text and "secret-sentinel" not in text


@pytest.mark.parametrize("change,reason", [
    ({"TRADIER_TOKEN": ""}, "MISSING_CREDENTIAL"),
    ({"TRADIER_INTERNAL_DATA_USE_AUTHORIZED": "false"}, "INTERNAL_USE_NOT_CONFIRMED"),
    ({"TRADIER_BASE_URL": "https://api.tradier.com.evil.test"}, "INVALID_ENDPOINT"),
    ({"TRADIER_BASE_URL": "https://secret@api.tradier.com"}, "INVALID_ENDPOINT"),
])
def test_blocked_does_not_make_requests(change, reason):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected network request")
    assert probe({**ENV, **change}, now=NOW, request=forbidden)["reason"] == reason


def test_sandbox_is_not_silently_promoted():
    def request(base, *args, **kwargs):
        assert base == "https://sandbox.tradier.com"
        return fake(base, *args, **kwargs)
    result = probe({**ENV, "TRADIER_BASE_URL": "https://sandbox.tradier.com"}, now=NOW, request=request)
    assert result["mode"] == "sandbox" and not result["ready"]


@pytest.mark.parametrize("change", [{"bid": float("nan")}, {"ask": float("inf")},
    {"bid": 0}, {"bid": 200}, {"bid_date": None}, {"bid": True},
    {"bid_date": NOW.timestamp() * 1000 + 1}, {"ask_date": NOW.timestamp() * 1000 - 121000}])
def test_bad_or_stale_quotes(change):
    assert not quote_quality(quote(**change), NOW)


def test_last_trade_timestamp_is_not_quote_timestamp():
    assert not quote_quality({"bid": 1, "ask": 2, "trade_date": NOW.timestamp() * 1000}, NOW)


def test_exceptions_do_not_leak_response_or_token():
    def fail(*args, **kwargs):
        raise ValueError("secret-sentinel protected-price")
    result = probe(ENV, now=NOW, request=fail)
    assert result["status"] == "UNAVAILABLE"
    assert "secret-sentinel" not in json.dumps(result)


def test_adjusted_option_identity_rejected():
    def request(*args, **kwargs):
        body = fake(*args, **kwargs)
        if "options" in body:
            body["options"]["option"]["symbol"] = "SPY1261023C00600000"
        return body
    assert probe(ENV, now=NOW, request=request)["status"] == "INCOMPLETE_RESPONSE"


def test_transport_never_follows_redirects(monkeypatch):
    class Response:
        status_code = 302
    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 15
        return Response()
    monkeypatch.setattr("scripts.preflight_tradier_free_live.requests.get", get)
    with pytest.raises(RuntimeError, match="HTTP_ACCESS_FAILED"):
        _request_json("https://api.tradier.com", "quotes", "secret")
