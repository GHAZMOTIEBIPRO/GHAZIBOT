from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

pytest.importorskip("yfinance")

import options_radar.catalysts as catalysts_module
from options_radar.catalysts import CatalystScanner, _score_text, best_catalyst_map
from options_radar.settings import Settings


def test_negative_financing_dominates_generic_positive_phrase() -> None:
    score, category, _ = _score_text(
        "The company announced a strategic partnership and a registered direct offering."
    )
    assert score < 0
    assert "offering" in category.lower()


def test_best_catalyst_map_applies_negative_risk_to_positive_event() -> None:
    frame = pd.DataFrame([
        {
            "symbol": "XYZ", "score": 20, "category": "FDA approval",
            "headline": "Approved", "url": "positive", "source": "SEC",
        },
        {
            "symbol": "XYZ", "score": -10, "category": "Offering",
            "headline": "Financing", "url": "negative", "source": "SEC",
        },
    ])
    result = best_catalyst_map(frame)["XYZ"]
    assert result["score"] == 10
    assert result["negative_score"] == -10


def test_sec_ticker_map_403_without_cache_degrades_instead_of_crashing(tmp_path, monkeypatch) -> None:
    scanner = CatalystScanner(Settings())
    scanner.cache_dir = tmp_path
    monkeypatch.setattr(catalysts_module, "LOCAL_CIK_MAP", tmp_path / "missing_sec_cik_map.json")

    def blocked(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response.url = "https://www.sec.gov/files/company_tickers.json"
        raise requests.HTTPError("403 Client Error: Forbidden", response=response)

    monkeypatch.setattr(scanner.session, "get", blocked)
    by_cik, by_ticker = scanner._ticker_map()

    assert by_cik == {}
    assert by_ticker == {}
    assert scanner._ticker_map() == ({}, {})


def test_sec_ticker_map_uses_checked_in_snapshot_when_live_endpoint_is_blocked(tmp_path, monkeypatch) -> None:
    scanner = CatalystScanner(Settings())
    scanner.cache_dir = tmp_path
    local_map = tmp_path / "sec_cik_map.json"
    local_map.write_text(json.dumps({"AAPL": "320193"}), encoding="utf-8")
    monkeypatch.setattr(catalysts_module, "LOCAL_CIK_MAP", local_map)

    def blocked(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response.url = "https://www.sec.gov/files/company_tickers.json"
        raise requests.HTTPError("403 Client Error: Forbidden", response=response)

    monkeypatch.setattr(scanner.session, "get", blocked)
    by_cik, by_ticker = scanner._ticker_map()

    assert by_cik["0000320193"] == ("AAPL", "AAPL")
    assert by_ticker["AAPL"] == "AAPL"


def test_sec_ticker_map_network_failure_uses_persisted_cache(tmp_path, monkeypatch) -> None:
    scanner = CatalystScanner(Settings())
    scanner.cache_dir = tmp_path
    monkeypatch.setattr(catalysts_module, "LOCAL_CIK_MAP", tmp_path / "missing_sec_cik_map.json")
    cache = tmp_path / "sec_company_tickers.json"
    cache.write_text(
        json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }),
        encoding="utf-8",
    )

    def offline(*args, **kwargs):
        raise requests.ConnectionError("SEC unavailable")

    monkeypatch.setattr(scanner.session, "get", offline)
    by_cik, by_ticker = scanner._ticker_map()

    assert by_cik["0000320193"] == ("AAPL", "Apple Inc.")
    assert by_ticker["AAPL"] == "Apple Inc."


def test_sec_events_use_official_submissions_when_current_feed_is_unavailable(tmp_path, monkeypatch) -> None:
    scanner = CatalystScanner(Settings())
    scanner.cache_dir = tmp_path
    local_map = tmp_path / "sec_cik_map.json"
    local_map.write_text(json.dumps({"AAPL": "320193"}), encoding="utf-8")
    monkeypatch.setattr(catalysts_module, "LOCAL_CIK_MAP", local_map)

    submissions = {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["8-K"],
                "filingDate": [catalysts_module.date.today().isoformat()],
                "accessionNumber": ["0000320193-26-000001"],
                "primaryDocument": ["aapl-8k.htm"],
            }
        },
    }

    def fake_get(url, *args, **kwargs):
        response = requests.Response()
        response.url = str(url)
        response.status_code = 200
        if str(url) == catalysts_module.SEC_TICKERS:
            response.status_code = 403
            response._content = b"forbidden"
            return response
        if str(url).startswith("https://data.sec.gov/submissions/CIK0000320193.json"):
            response._content = json.dumps(submissions).encode("utf-8")
            response.encoding = "utf-8"
            return response
        if "/Archives/edgar/data/320193/" in str(url):
            response._content = b"<html><body>The company announced a strategic partnership.</body></html>"
            response.encoding = "utf-8"
            return response
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(scanner.session, "get", fake_get)
    events = scanner._sec_events({"AAPL"})

    assert scanner._sec_submissions_usable is True
    assert len(events) == 1
    assert events[0].symbol == "AAPL"
    assert events[0].source == "SEC EDGAR submissions"
    assert events[0].score > 0
    assert "partnership" in events[0].category.lower()
