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
    parse_occ_market_oi,
    parse_occ_series_oi,
)

NOW = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
CIK = 320193

# Synthetic numbers in the exact layouts a GitHub runner probe observed
# (digit-masked) from marketdata.theocc.com in October 2026.
MARKET_OI = (
    "Daily Open Interest - October 2026\n"
    "Date,Equity,,,Index/Other,,,Debt,,,Futures,OCC Total\n"
    ",Calls,Puts,Total,Calls,Puts,Total,Calls,Puts,Total,Total,\n"
    '10/15/2026,"200,000,000","150,000,000","350,000,000","20,000,000",'
    '"25,000,000","45,000,000",0,0,0,"500,000","395,500,000",\n'
    '10/16/2026,"201,000,000","151,000,000","352,000,000","20,000,000",'
    '"25,000,000","45,000,000",0,0,0,"500,000","397,500,000",\n'
)


def series(symbol: str, rows: list[str]) -> str:
    return (
        f"Series Search Results for {symbol}\n"
        "Products for this underlying symbol are traded on:\n"
        "AMEX ARCA BATS BOX C2 CBOE\n"
        "\t\tSeries/contract\t\tStrike\t\t\tOpen Interest\t\t\t\n"
        "ProductSymbol\tyear\tMonth\tDay\tInteger\tDec\tC/P\tCall\tPut\tPosition Limit\t\n"
        + "".join(row + "\n" for row in rows)
    )


AAPL_SERIES = series("AAPL", [
    "AAPL\t\t2026\t10\t23\t250\t000\tC P\t1200\t800\t25000000",
    "AAPL\t\t2026\t11\t20\t260\t000\tC P\t300\t700\t25000000",
    "2AAPL\t\t2026\t11\t20\t130\t000\tC\t999\t0\t25000000",
])


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
            if url.endswith("/daily-open-interest"):
                payload = MARKET_OI.encode()
            elif params["symbol"] == "AAPL":
                payload = AAPL_SERIES.encode()
            else:
                payload = series(params["symbol"], [
                    f"{params['symbol']}\t\t2026\t11\t20\t10\t500\tC P\t40\t60\t25000000",
                ]).encode()
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


def test_occ_market_report_is_market_wide_and_dates_publication_only():
    market = parse_occ_market_oi(MARKET_OI)
    assert market == {
        "status": "MARKET_WIDE_DAILY_TOTALS", "report_date": "2026-10-16",
        "equity_call_oi": 201_000_000, "equity_put_oi": 151_000_000,
        "equity_total_oi": 352_000_000, "occ_total_oi": 397_500_000,
    }
    # The title alone (the production layout before) is never a sample.
    assert parse_occ_market_oi("Daily Open Interest - October 2026\n")[
        "status"] == "UNKNOWN_LAYOUT"
    assert parse_occ_market_oi("<html>Error</html>")["status"] == "UNPARSEABLE_CSV"
    # Calls + puts must equal the reported equity total; no repair.
    broken = MARKET_OI.replace('"352,000,000"', '"352,000,001"')
    assert parse_occ_market_oi(broken)["status"] == "INVALID_ROW"
    unknown = parse_occ_market_oi("stock,price\nAAPL,12\n")
    assert unknown["status"] == "UNKNOWN_LAYOUT"
    assert "AAPL" not in str(unknown) and "12" not in str(unknown)


def test_occ_series_sums_standard_contracts_and_excludes_adjusted():
    parsed = parse_occ_series_oi(AAPL_SERIES, symbol="AAPL")
    assert parsed == {
        "status": "SERIES_OPEN_INTEREST", "call_oi": 1500, "put_oi": 1500,
        "total_oi": 3000, "put_call_oi_ratio": 1.0,
        "standard_series": 2, "nonstandard_series_excluded": 1,
    }
    only_adjusted = series("AAPL", [
        "2AAPL\t\t2026\t11\t20\t130\t000\tC\t999\t0\t25000000"])
    assert parse_occ_series_oi(only_adjusted, symbol="AAPL") == {
        "status": "NO_STANDARD_SERIES", "nonstandard_series_excluded": 1}
    bad = series("AAPL", ["AAPL\t\t2026\t13\t20\t250\t000\tC P\t1\t2\t9"])
    assert parse_occ_series_oi(bad, symbol="AAPL")["status"] == "INVALID_ROW"
    negative = series("AAPL", ["AAPL\t\t2026\t11\t20\t250\t000\tC P\t-1\t2\t9"])
    assert parse_occ_series_oi(negative, symbol="AAPL")["status"] == "INVALID_ROW"
    assert parse_occ_series_oi("Series Search Results for AAPL\n",
                               symbol="AAPL")["status"] == "UNKNOWN_LAYOUT"


def test_occ_snapshot_dates_only_from_market_report_and_stays_context():
    cli = FakeSession()
    report = occ_open_interest_snapshot(now=NOW, session=cli, enabled=True, pause=0)
    assert report["status"] == "HISTORICAL_DAILY_AGGREGATE"
    assert report["not_live_quote"] is True
    assert report["not_trade_flow"] is True
    assert report["report_date"] == "2026-10-16"
    assert report["report_date_scope"] == "OCC_MARKET_WIDE_DAILY_REPORT"
    assert report["per_symbol_as_of_verified"] is False
    assert report["per_symbol_retrieved_at"] == NOW.isoformat()
    assert report["open_interest"] == {"AAPL": 3000, "NVDA": 100,
                                       "TSLA": 100, "SOFI": 100}
    assert report["per_symbol"]["AAPL"]["nonstandard_series_excluded"] == 1
    occ_calls = [entry for entry in cli.calls if "theocc.com" in entry[0]]
    assert occ_calls[0][1] == {
        "reportDate": "10/16/2026", "action": "download", "format": "csv",
    }
    assert [c[1] for c in occ_calls[1:]] == [
        {"symbolType": "U", "symbol": s} for s in ("AAPL", "NVDA", "TSLA", "SOFI")]


def test_occ_stale_or_missing_market_report_fails_closed():
    later = NOW.replace(month=11, day=2)
    stale = occ_open_interest_snapshot(now=later, session=FakeSession(),
                                       enabled=True, pause=0)
    assert stale["status"] == "STALE_MARKET_REPORT"
    assert stale["open_interest"] is None and stale["report_date"] is None

    class Denied(FakeSession):
        def get(self, url, **kwargs):
            self.calls.append((url, kwargs.get("params"), None))
            return SimpleNamespace(status_code=406, iter_content=lambda chunk_size: iter([]))

    denied = Denied()
    report = occ_open_interest_snapshot(now=NOW, session=denied, enabled=True, pause=0)
    assert report["status"] == "HTTP_406"
    assert report["open_interest"] is None
    assert len(denied.calls) == 1


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
