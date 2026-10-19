"""No network, no accounts: fail-closed free options source checks."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.build_free_options_sources import (
    _issuer_records,
    _official_sec_link,
    collect,
    filingpulse_snapshot,
    occ_open_interest_snapshot,
    parse_occ_oi_csv,
)

NOW = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
CIK = 320193


class FakeSession:
    def __init__(self, *, key_present: bool = False, bad_issuer: bool = False,
                 blocked: bool = False):
        self.calls = []
        self.key_present = key_present
        self.bad_issuer = bad_issuer
        self.blocked = blocked

    def get(self, url, *, params=None, headers=None, timeout=None,
            stream=False):
        self.calls.append((url, params, headers))
        if "marketdata.theocc.com" in url:
            payload = b"Underlying Symbol,Open Interest\nAAPL,1234\nNVDA,400\n"
            return SimpleNamespace(
                status_code=200, iter_content=lambda chunk_size: iter([payload]),
            )
        assert url.startswith("https://api.filingpulse.io/v1/")
        if url.endswith("/health"):
            return SimpleNamespace(status_code=200, content=b'{"status":"ok"}',
                                   json=lambda: {"status": "ok"})
        if self.blocked:
            return SimpleNamespace(status_code=429, content=b"{}",
                                   json=dict)
        assert headers["X-API-Key"] == "fp_example"
        assert "cik" in params and "since" in params and "until" in params
        if url.endswith("/events"):
            event = {
                "issuer": {"cik": "9999" if self.bad_issuer else "0000320193",
                           "name": "Apple Inc."},
                "filed_date": "20261016", "form_type": "8-K",
                "accession": "0000320193-26-000003",
                "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000003/test.html",
                "items": [{"code": "2.02", "caption": "Earnings"}],
            }
            body = {"data": [event], "total": 1, "offset": 0, "limit": 30}
        else:
            body = {"data": [], "total": 0, "offset": 0, "limit": 30}
        return SimpleNamespace(status_code=200, content=b'{"data":[]}',
                               json=lambda: body)


def test_no_key_only_queries_public_health_and_keeps_unverified_filing_status():
    client = FakeSession()
    report = collect(now=NOW, ciks={"AAPL": CIK},
                     key="", occ_enabled=False, session=client)
    assert report["trading_authority"] is False
    assert report["option_execution_eligible"] is False
    assert report["filingpulse"]["health_reachable"] is True
    assert report["filingpulse"]["status"] == "NO_API_KEY_HEALTH_ONLY"
    assert not report["filingpulse"]["events"]
    assert report["occ_open_interest"]["status"] == "DISABLED"
    assert len(client.calls) == 1
    assert client.calls[0][0].endswith("/health")


def test_free_key_events_require_issuer_cik_accession_date_and_sec_link():
    client = FakeSession(key_present=True)
    report = filingpulse_snapshot(key="fp_example", ciks={"AAPL": CIK},
                                  now=NOW, session=client)
    assert report["status"] == "THIRD_PARTY_RESEARCH_ONLY"
    assert report["api_calls_attempted"] == 3
    assert len(report["events"]) == 1
    row = report["events"][0]
    assert row["item_codes"] == ["2.02"]
    assert row["filed_date"] == "2026-10-16"
    assert row["official_sec_api_response_verified"] is False
    assert row["positive_catalyst_verified"] is False
    assert row["source_url"].startswith("https://www.sec.gov/Archives")
    assert _official_sec_link("https://bad.example.org/Archives/edgar/data/x") is None
    assert _official_sec_link("https://www.sec.gov@evil.com/Archives/edgar/data/1") is None
    assert _official_sec_link("http://www.sec.gov/Archives/edgar/data/1") is None


def test_filingpulse_cik_mismatch_or_quota_does_not_make_up_filing():
    rejected = filingpulse_snapshot(
        key="fp_example", ciks={"AAPL": CIK}, now=NOW,
        session=FakeSession(bad_issuer=True),
    )
    assert rejected["events"] == []
    assert rejected["status"] == "NO_VERIFIED_RECENT_METADATA"
    limited = filingpulse_snapshot(
        key="fp_example", ciks={"AAPL": CIK}, now=NOW,
        session=FakeSession(blocked=True),
    )
    assert limited["status"] == "RATE_LIMIT_OR_QUOTA_EXHAUSTED"
    assert limited["quota_exhausted"] is True
    assert limited["events"] == []


def test_occ_csv_and_one_daily_download_are_context_only():
    good = parse_occ_oi_csv("Underlying Symbol,Open Interest\nAAPL,100\nTSLA,200\n",
                            watched={"AAPL", "TSLA"})
    assert good["status"] == "HISTORICAL_DAILY_AGGREGATE"
    assert good["watched_oi"] == {"AAPL": 100, "TSLA": 200}
    # The actual OCC download may prepend an aggregate/report-period title.
    with_title = parse_occ_oi_csv(
        "Daily Open Interest October 2026\n"
        "For clearing-member reference only\n"
        "Underlying Symbol,Open Interest\n"
        "AAPL,100\nNVDA,250\n",
        watched={"AAPL", "NVDA"},
    )
    assert with_title["status"] == "HISTORICAL_DAILY_AGGREGATE"
    assert with_title["watched_oi"] == {"AAPL": 100, "NVDA": 250}
    # A report heading alone must NEVER be treated as a positive OI sample.
    assert parse_occ_oi_csv(
        "Daily Open Interest October 2026\nAAPL,100\n",
        watched={"AAPL"},
    )["status"] == "UNKNOWN_LAYOUT"
    assert parse_occ_oi_csv("<html>Error</html>", watched={"AAPL"})["matched"] == 0
    bad_schema = parse_occ_oi_csv(
        "stock,price\nAAPL,12\n", watched={"AAPL"}
    )
    assert bad_schema["status"] == "UNKNOWN_LAYOUT"
    assert bad_schema["safe_schema_column_names"] == ["stock", "price"]
    assert "AAPL" not in str(bad_schema)
    assert "12" not in str(bad_schema)
    cli = FakeSession()
    report = occ_open_interest_snapshot(now=NOW, session=cli, enabled=True)
    assert report["status"] == "HISTORICAL_DAILY_AGGREGATE"
    assert report["not_live_quote"] is True
    assert report["not_trade_flow"] is True
    assert report["open_interest"]["AAPL"] == 1234
    assert sum("theocc.com" in entry[0] for entry in cli.calls) == 1
    occ_calls = [entry for entry in cli.calls if "theocc.com" in entry[0]]
    assert occ_calls[0][1] == {
        "reportDate": "10/16/2026", "action": "download", "format": "csv",
    }


def test_filingpulse_must_match_date_and_form():
    valid = {"data": [
        {"issuer": {"cik": "320193"}, "filed_date": "20261016",
         "form_type": "8-K", "accession": "0000320193-26-000001",
         "source_url": "https://www.sec.gov/Archives/edgar/data/320193/1/2.htm",
         "items": [{"code": "3.02"}]},
        {"issuer": {"cik": "320193"}, "filed_date": "20260101",
         "form_type": "8-K", "accession": "0000320193-26-000002",
         "source_url": "https://www.sec.gov/Archives/edgar/data/320193/1/3.htm",
         "items": [{"code": "2.02"}]},
    ]}
    from datetime import date

    rows = _issuer_records(valid, symbol="AAPL", cik=320193,
                           kind="event", since=date(2026, 10, 14),
                           until=date(2026, 10, 19))
    assert len(rows) == 1
    assert rows[0]["item_codes"] == ["3.02"]
