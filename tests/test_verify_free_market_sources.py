"""Official provider health tests: all network mocked; no live quote or key leaks."""
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import verify_free_market_sources as audit

NOW = datetime(2026, 10, 30, 19, 15, tzinfo=timezone.utc)
OWNER = {
    "TWELVE_DATA_API_KEY": "TwelvePrivateCredential",
    "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED": "true",
    "ALPACA_API_KEY": "AlpacaPrivateID",
    "ALPACA_SECRET_KEY": "AlpacaPrivateSecret",
    "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
    "TRADIER_TOKEN": "TradierPrivateCredential",
    "TRADIER_INTERNAL_DATA_USE_AUTHORIZED": "true",
    "TRADIER_BASE_URL": "https://sandbox.tradier.com",
    "SEC_USER_AGENT": "ResearchOperator real-contact@example.org",
    "DATA_TERMS_CONFIRMED": "alpaca,twelve_data,tradier",
}


class Reply:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.content = json.dumps(payload).encode()
    def json(self):
        return self.payload


class Recorder:
    def __init__(self, *, status=200):
        self.calls = []
        self.status = status
    def get(self, url, headers, params, timeout, allow_redirects):
        assert allow_redirects is False and timeout == 12
        self.calls.append((url, headers, params))
        if self.status != 200:
            return Reply({}, self.status)
        if url.startswith("https://api.twelvedata.com/"):
            rows = []
            for d in (27, 28, 29):
                rows.append({"datetime": f"2026-10-{d:02d}",
                             "open": "700", "high": "710", "low": "695",
                             "close": "704.5", "volume": "1100000"})
            return Reply({"status": "ok", "meta": {"symbol": "SPY"}, "values": rows})
        if "/v2/stocks/SPY/bars" in url:
            return Reply({"bars": [
                {"o": 700, "h": 710, "l": 690, "c": 704},
                {"o": 701, "h": 712, "l": 700, "c": 706}]})
        if "/v1beta1/options/snapshots/" in url:
            return Reply({"snapshots": {
                "SPY261102C00750000": {"latest_quote": {"bid_price": 3.0,
                                                       "ask_price": 3.1},
                                       "greeks": {"gamma": .04}}}})
        if "/v1/markets/quotes" in url:
            return Reply({"quotes": {"quote": {
                "symbol": "SPY", "type": "etf", "last": 705.3}}})
        if "/v1/markets/options/expirations" in url:
            return Reply({"expirations": {"date": ["2026-11-02", "2026-11-03"]}})
        if "data.sec.gov" in url:
            return Reply({"cik": 320193, "filings": {
                "recent": {"accessionNumber": ["0000320193-26-000100"]}}})
        raise AssertionError("Unapproved destination")


def test_absent_keys_and_attestations_mean_zero_network():
    class NoNetwork:
        def get(self, *_args, **_kwargs):
            raise AssertionError("Never access account data by default")
    result = audit.run({}, now=NOW, session=NoNetwork())
    assert result["real_data_providers_verified"] == 0
    assert result["allowed_to_generate_execution_alerts"] is False
    assert all(v["requests"] == 0 for v in result["providers"].values())
    assert all(not v["data_verified"] for v in result["providers"].values())


def test_credentials_not_sufficient_without_owner_confirmed_terms():
    env = dict(OWNER)
    env.pop("DATA_TERMS_CONFIRMED")
    env.pop("SEC_USER_AGENT")
    result = audit.run(env, now=NOW, session=Recorder())
    assert all(v["requests"] == 0 for v in result["providers"].values())
    assert result["providers"]["twelve_data"]["status"] == "OWNER_TERMS_NOT_CONFIRMED"
    assert result["providers"]["tradier"]["status"] == "OWNER_TERMS_NOT_CONFIRMED"


def test_real_structures_verified_and_private_only():
    session = Recorder()
    result = audit.run(OWNER, now=NOW, session=session)
    assert result["real_data_providers_verified"] == 4
    assert result["providers"]["twelve_data"]["status"] == "INTERNAL_DAILY_BARS_VERIFIED"
    assert result["providers"]["alpaca"]["status"] == "IEX_AND_INDICATIVE_OPTIONS_VERIFIED"
    assert result["providers"]["tradier"]["status"] == "STOCK_AND_EXPIRIES_VERIFIED"
    assert result["providers"]["sec_edgar"]["status"] == "OFFICIAL_FILINGS_VERIFIED"
    assert len(session.calls) == 6
    for row in result["providers"].values():
        assert row["execution_grade"] is False
        assert row["public_redistribution_allowed"] is False
    serialized = json.dumps(result)
    for secret in ("TwelvePrivateCredential", "AlpacaPrivateID", "AlpacaPrivateSecret",
                   "TradierPrivateCredential", "real-contact@example.org", "705.3",
                   "704.5", "710"):
        assert secret not in serialized


def test_no_automated_tradier_credential_on_unapproved_host():
    env = dict(OWNER, TRADIER_BASE_URL="https://evil.example.org")
    session = Recorder()
    report = audit.probe_tradier(env, session, NOW)
    assert report["status"] == "INVALID_APPROVED_ENDPOINT"
    assert session.calls == []


def test_quota_and_access_denied_dont_produce_success():
    result = audit.run(OWNER, now=NOW, session=Recorder(status=429))
    assert result["real_data_providers_verified"] == 0
    assert all(row["status"] == "QUOTA_EXHAUSTED" for row in result["providers"].values())


def test_sec_invalid_agent_does_not_hit_provider():
    env = dict(OWNER, SEC_USER_AGENT="AnonymousBot/1.0")
    session = Recorder()
    result = audit.probe_sec(env, session, NOW)
    assert result["status"] == "INVALID_USER_AGENT"
    assert session.calls == []


def test_source_audit_is_in_existing_read_only_private_workflow():
    text = (Path(".github/workflows/settings-check.yml")
            .read_text(encoding="utf-8"))
    assert "python -m scripts.verify_free_market_sources" in text
    assert '$RUNNER_TEMP/ghazi_free_source_health.json' in text
    assert "schedule:" in text and 'branches: [main, "ccr-**"]' in text
    assert "contents: read" in text and "actions: read" in text
    assert "upload-artifact" not in text and "git add" not in text
    for name in ("TWELVE_DATA_API_KEY", "TRADIER_TOKEN", "SEC_USER_AGENT",
                 "ALPACA_SECRET_KEY"):
        assert f"{name}: ${{{{ secrets.{name} }}}}" in text
