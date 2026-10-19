"""Opt-in Alpaca research and SEC resilience tests (network disabled)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import requests

from options_radar.alpaca_delayed_research import (
    fetch_completed_daily,
    historical_option_response,
    policy_state,
)
from scripts.build_sec_filing_pulse import (
    FALLBACK_TICKER_MAP,
    SUBMISSIONS_BASE,
    TICKERS_URL,
    candidate_local_cik_map,
    collect,
)

NOW = datetime(2026, 10, 19, 11, tzinfo=timezone.utc)
OPTION = "AAPL261120C00150000"


class NeverGet:
    def get(self, *args, **kwargs):
        raise AssertionError("Access attempted despite missing permission")


class AlpacaFixture:
    def __init__(self, rows, *, mode: str = "stock", status: int = 200,
                 pagination: bool = False):
        self.rows = rows
        self.mode = mode
        self.status = status
        self.pagination = pagination
        self.calls = 0

    def get(self, url, *, params, headers, timeout):
        self.calls += 1
        assert timeout <= 12
        assert headers["APCA-API-KEY-ID"] == "id"
        assert headers["APCA-API-SECRET-KEY"] == "private"
        if self.mode == "stock":
            assert "/v2/stocks/AAPL/bars" in url
            assert params["feed"] == "iex"
            assert params["adjustment"] == "raw"
            payload = {"bars": self.rows}
        else:
            assert "/v1beta1/options/bars" in url
            assert params["symbols"] == OPTION
            payload = {"bars": {OPTION: self.rows}}
        if self.pagination:
            payload["next_page_token"] = "MORE_PAGES_UNCHECKED"
        return SimpleNamespace(content=b'{"bars":[]}', status_code=self.status,
                               json=lambda: payload)


def candle(day: str, close: float) -> dict:
    return {"t": day + "T16:00:00Z",
            "o": close, "h": close + 1, "l": close - 1,
            "c": close, "v": 1000}


def test_absent_permission_never_calls_provider_or_claims_execution():
    out = fetch_completed_daily(
        "AAPL", start=date(2026, 10, 15), end=date(2026, 10, 16),
        api_key="id", secret="private", internal_use_allowed=False,
        now=NOW, session=NeverGet(),
    )
    assert out["enabled"] is False
    assert out["reason"] == "DATA_USE_PERMISSION_REQUIRED"
    assert out["public_redistribution_allowed"] is False
    assert out["live_opra_quotes"] is False
    assert not policy_state(api_key="", secret="", internal_use_allowed=True)["enabled"]


def test_iex_is_single_exchange_not_a_verified_sip_quote():
    session = AlpacaFixture([candle("2026-10-15", 100),
                             candle("2026-10-16", 104)])
    result = fetch_completed_daily(
        "AAPL", start=date(2026, 10, 15), end=date(2026, 10, 16),
        api_key="id", secret="private", internal_use_allowed=True,
        now=NOW, session=session,
    )
    assert session.calls == 1
    assert result["status"] == "HISTORICAL_RESEARCH_BARS"
    assert result["exchange_scope"] == "IEX_ONLY"
    assert result["bars"][0]["source_feed"] == "IEX"
    assert result["execution_eligible"] is False
    assert result["public_redistribution_allowed"] is False
    assert len(result["bars"]) == 2


def test_dated_options_bars_are_not_realtime_opra_or_pnl():
    source = AlpacaFixture([candle("2026-10-15", 2.0),
                            candle("2026-10-16", 3.0)], mode="option")
    result = historical_option_response(
        OPTION, entry_date=date(2026, 10, 15),
        end_date=date(2026, 10, 16), api_key="id",
        secret="private", internal_use_allowed=True,
        now=NOW, session=source,
    )
    assert source.calls == 1
    assert result["status"] == "HISTORICAL_CLOSE_OBSERVATION"
    assert result["observed_close_change_pct"] == 50
    assert result["realized_pnl"] is None
    assert result["fill_price"] is None
    assert result["execution_eligible"] is False
    assert result["opra_execution_quotes_verified"] is False
    assert result["public_redistribution_allowed"] is False


def test_no_access_current_day_or_bad_symbols_or_partial_pages():
    kwargs = {"api_key": "id", "secret": "private",
              "internal_use_allowed": True, "now": NOW,
              "session": NeverGet()}
    for symbol in ("../../AAPL", "SPY?feed=sip"):
        assert fetch_completed_daily(
            symbol, start=date(2026, 10, 15),
            end=date(2026, 10, 16), **kwargs)["bars"] == []
    assert fetch_completed_daily(
        "AAPL", start=date(2026, 10, 18),
        end=date(2026, 10, 19), **kwargs)["reason"] == (
            "INVALID_OR_UNFINISHED_DAILY_WINDOW"
        )
    partial = AlpacaFixture([candle("2026-10-16", 100)], pagination=True)
    data = fetch_completed_daily(
        "AAPL", start=date(2026, 10, 16),
        end=date(2026, 10, 16), api_key="id", secret="private",
        internal_use_allowed=True, now=NOW, session=partial,
    )
    assert data["bars"] == []


def test_local_cik_official_confirmation_when_map_request_unavailable(tmp_path):
    local = tmp_path / "cik.json"
    local.write_text(json.dumps({"RGC": "0000000111"}), encoding="utf-8")
    assert candidate_local_cik_map(local)["RGC"][0] == 111
    refused = requests.HTTPError(
        "403", response=SimpleNamespace(status_code=403)
    )
    valid = {"cik": 111, "name": "Official Issuer", "tickers": ["RGC"],
             "filings": {"recent": {
                 "form": ["8-K"], "filingDate": ["2026-10-16"],
                 "accessionNumber": ["0000000111-26-000001"],
                 "primaryDocument": ["item.htm"], "items": ["2.02"],
             }}}
    class SECStub:
        calls = 0
        def get(self, url, *, headers, timeout):
            self.calls += 1
            if url == TICKERS_URL:
                raise refused
            if url == FALLBACK_TICKER_MAP:
                raise requests.ConnectionError("offline")
            assert url == SUBMISSIONS_BASE + "CIK0000000111.json"
            return SimpleNamespace(
                content=b'{"ok":true}', raise_for_status=lambda: None,
                json=lambda: valid,
            )
    session = SECStub()
    report = collect(
        {"stocks": []}, now=NOW, session=session, pause=lambda _: None,
        agent="Research real-contact@example.com", max_symbols=1,
        local_cik_path=local,
    )
    assert session.calls == 3
    assert report["ticker_mapping_source"] == (
        "LOCAL_CIK_INDEX_REQUIRES_OFFICIAL_CONFIRMATION"
    )
    assert report["coverage"]["filings_verified"] == 1
    assert report["filings"][0]["issuer"] == "Official Issuer"
    assert report["status"] == "PARTIAL"
    forged = {**valid, "tickers": ["WRONG"]}
    class RejectSEC(SECStub):
        def get(self, url, *, headers, timeout):
            if url == TICKERS_URL:
                raise refused
            if url == FALLBACK_TICKER_MAP:
                raise requests.ConnectionError("offline")
            return SimpleNamespace(content=b"{}", raise_for_status=lambda: None,
                                   json=lambda: forged)
    blocked = collect(
        {"stocks": []}, now=NOW, session=RejectSEC(), pause=lambda _: None,
        agent="Research real-contact@example.com", max_symbols=1,
        local_cik_path=local,
    )
    assert blocked["filings"] == []
    assert blocked["coverage"]["filings_verified"] == 0


def test_sec_cooldown_never_bypassed_by_local_cik(tmp_path):
    local = tmp_path / "cik.json"
    local.write_text(json.dumps({"RGC": 111}), encoding="utf-8")
    previous = {"schema": "ghazi.sec_issuer_pulse.v1",
                "source_retry_after": "2026-10-19T13:00:00+00:00",
                "refusal_reason": "HTTP_403", "generated_at": NOW.isoformat()}
    result = collect(
        {"stocks": []}, now=NOW, session=NeverGet(), pause=lambda _: None,
        agent="Research contact@example.com", max_symbols=1,
        previous=previous, local_cik_path=local,
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["filings"] == []
    assert result["coverage"]["errors"]["sec_api"] == "COOLDOWN_ACTIVE"
