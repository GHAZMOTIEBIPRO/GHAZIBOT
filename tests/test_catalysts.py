from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

pytest.importorskip("yfinance")

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

    def blocked(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response.url = "https://www.sec.gov/files/company_tickers.json"
        raise requests.HTTPError("403 Client Error: Forbidden", response=response)

    monkeypatch.setattr(scanner.session, "get", blocked)
    by_cik, by_ticker = scanner._ticker_map()

    assert by_cik == {}
    assert by_ticker == {}
    # A second call uses the in-memory result and does not retry the blocked endpoint.
    assert scanner._ticker_map() == ({}, {})


def test_sec_ticker_map_network_failure_uses_persisted_cache(tmp_path, monkeypatch) -> None:
    scanner = CatalystScanner(Settings())
    scanner.cache_dir = tmp_path
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
