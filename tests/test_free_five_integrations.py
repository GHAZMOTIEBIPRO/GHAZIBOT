"""No-key, offline, fail-closed tests for five research integrations."""
from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timezone
from types import SimpleNamespace

from options_radar.data_fabric import (
    optional_historical_option_eod_audit,
    optional_independent_eod_research,
)
from options_radar.optional_massive_research import (
    fetch_eod,
    permission_state,
    validate_daily_aggregates,
)
from options_radar.options_daily_outcome_shadow import describe_option_path
from options_radar.sec_bulk_fallback import read_issuer
from options_radar.stock_walk_forward import coverage_gap_diagnostics
from scripts.build_sec_filing_pulse import collect
from scripts.build_source_consensus_status import summarize

NOW = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
CONTRACT = "O:AAPL261120C00150000"


class TrapSession:
    def get(self, *args, **kwargs):
        raise AssertionError("No API request may occur without license/key")


def test_massive_gated_before_network_even_with_free_api_key():
    r = fetch_eod("AAPL", key="free-key-not-permission", permitted=False,
                  end_date=date(2026, 10, 16), session=TrapSession())
    assert r["reason"] == "NONDISPLAY_LICENSE_NOT_CONFIRMED"
    assert r["bars"] == [] and not r["enabled"]
    wrapped = optional_independent_eod_research(
        "AAPL", end_date=date(2026, 10, 16),
        key="free-key-not-permission", licensed=False, session=TrapSession())
    assert wrapped["enabled"] is False
    assert wrapped["bars"] == []
    assert permission_state(key="", permitted=True)["reason"] == "API_KEY_NOT_CONFIGURED"


def test_massive_explicitly_licensed_internal_daily_bars_only():
    payload = {"ticker": "AAPL", "status": "OK", "results": [
        {"t": 1792108800000, "o": 100, "h": 110, "l": 95, "c": 105, "v": 550},
        {"t": 1792195200000, "o": 105, "h": 109, "l": 100, "c": 101, "v": 620},
    ]}
    class Stub:
        def get(self, url, *, params, timeout):
            assert "/AAPL/range/1/day/" in url
            assert params["adjusted"] == "false"
            assert params["apiKey"] == "licensed-secret"
            return SimpleNamespace(status_code=200, content=b'{}',
                                   json=lambda: payload)
    result = fetch_eod("AAPL", key="licensed-secret", permitted=True,
                       end_date=date(2026, 10, 17), session=Stub())
    assert result["reason"] == "RESEARCH_BARS"
    assert result["internal_only"] is True
    assert result["execution_eligible"] is False
    assert len(result["bars"]) == 2
    assert validate_daily_aggregates(
        {**payload, "ticker": "TSLA"}, "AAPL",
        end_date=date(2026, 10, 17)) == []
    assert fetch_eod("../../bad", key="yes", permitted=True,
                     end_date=date(2026, 10, 17),
                     session=TrapSession())["reason"] == "INVALID_REQUEST"


def test_option_history_is_observation_not_execution_success():
    bars = [
        {"date": "2026-10-15", "close": 1.8},
        {"date": "2026-10-16", "close": 2.1},
        {"date": "2026-10-19", "close": 2.7},
    ]
    result = describe_option_path(CONTRACT, bars, entry_date="2026-10-15",
                                  end_date="2026-10-19")
    assert result["status"] == "HISTORICAL_CLOSE_OBSERVATION"
    assert result["observed_close_change_pct"] == 50.0
    assert result["realized_pnl"] is None
    assert result["fill_price"] is None
    assert result["win_rate"] is None
    assert result["execution_eligible"] is False
    assert describe_option_path(CONTRACT, bars[1:], entry_date="2026-10-15",
                                end_date="2026-10-19")["status"] == "UNAVAILABLE"


def test_offline_sec_zip_must_confirm_original_issuer_identity(tmp_path):
    archive = tmp_path / "sec-bulk.zip"
    payload = {
        "cik": 111, "name": "Example Issuer", "tickers": ["RGC"],
        "filings": {"recent": {
            "form": ["8-K"], "filingDate": ["2026-10-18"],
            "accessionNumber": ["0000000111-26-000001"],
            "primaryDocument": ["filing.htm"], "items": ["2.02"],
        }},
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("CIK0000000111.json", json.dumps(payload))
    assert read_issuer(archive, 111, "RGC")["name"] == "Example Issuer"
    assert read_issuer(archive, 111, "TSLA") is None
    assert read_issuer(archive, 222, "RGC") is None
    cik = tmp_path / "map.json"
    cik.write_text(json.dumps({"RGC": "0000000111"}), encoding="utf-8")
    report = collect(
        {"stocks": []}, now=NOW, session=TrapSession(),
        agent="Test analyst@example.com", pause=lambda _: None,
        max_symbols=1, bulk_archive=archive,
        bulk_cik_map=cik, bulk_official_origin_attested=True,
    )
    assert report["status"] == "BULK_ARCHIVE_UNDATED"
    assert report["coverage"]["filings_verified"] == 1
    assert report["filings"][0]["earnings_release_reported"] is True
    assert report["filings"][0]["official_live_response_verified"] is False
    assert report["source_observed_at"] is None
    assert report["policy"]["offline_archive_not_live"] is True


def test_oos_coverage_gap_counts_missing_actual_bars_not_fabricated_wins():
    audit = {"coverage": {"eligible_records": 689, "covered_60m": 442}}
    d = coverage_gap_diagnostics(audit)
    assert d["eligible_records"] == 689
    assert d["covered_60m_records"] == 442
    assert d["missing_60m_records"] == 247
    assert d["minimum_required_60m_records"] == 621
    assert d["additional_records_needed_at_fixed_denominator"] == 179
    assert coverage_gap_diagnostics({})["coverage_deficit_known"] is False


def test_public_consensus_never_exposes_private_prices_or_fake_second_feed():
    payload = summarize({
        "schema": "ghazi.stock_charts.v1",
        "quote_execution_eligible": False,
        "provider_source_family": "yahoo",
        "coverage": {"with_valid_charts": 20},
    }, now=NOW)
    assert payload["source_price_families"] == ["yahoo"]
    assert payload["independent_confirmations"] == 0
    assert payload["independent_price_comparison"] == "NOT_VERIFIED"
    assert payload["massive_market_data_published"] is False
    assert payload["price_data"] is None
    assert "apiKey" not in json.dumps(payload)
    assert summarize({}, now=NOW)["source_charts_available"] is False


def test_historical_options_adapter_respects_entitlement_and_no_trades():
    result=optional_historical_option_eod_audit(
        CONTRACT,entry_date=date(2026,10,15),exit_date=date(2026,10,19),
        key="free-key",licensed=False,session=TrapSession())
    assert result["reason"]=="NONDISPLAY_LICENSE_NOT_CONFIRMED"
    assert result["realized_pnl"] is None
    assert result["execution_eligible"] is False
