from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from options_radar.hybrid_fetcher import DataFetcher, DataUnavailableError
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings


def test_marketdata_free_history_parses_daily_contract_volume(monkeypatch):
    settings = Settings(
        marketdata_token="free-test-token",
        tradier_token=None,
        option_history_provider_order="marketdata,tradier",
    )
    fetcher = DataFetcher(settings)
    captured = {}

    def fake_get_json(url, *, params=None, headers=None, sec=False):
        captured.update(
            {"url": url, "params": params, "headers": headers, "sec": sec}
        )
        return {
            "s": "ok",
            "updated": [1791331200, 1791417600, 1791504000],
            "volume": [100, 140, 520],
            "openInterest": [1000, 1010, 1020],
            "bid": [2.0, 2.1, 2.5],
            "ask": [2.2, 2.3, 2.7],
            "last": [2.1, 2.2, 2.6],
            "underlyingPrice": [100, 101, 104],
        }

    monkeypatch.setattr(fetcher, "_get_json", fake_get_json)
    result = fetcher.fetch_option_volume_history(
        "ABC261120C00100000",
        start=datetime(2026, 10, 1, tzinfo=timezone.utc),
        end=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )

    assert result.source == "marketdata"
    assert result.metadata["execution_grade"] is False
    assert result.metadata["historical_greeks_available"] is False
    assert result.data["Volume"].tolist() == [100.0, 140.0, 520.0]
    assert result.data["OpenInterest"].tolist() == [1000.0, 1010.0, 1020.0]
    assert isinstance(result.data.index, pd.DatetimeIndex)
    assert str(result.data.index.tz) == "UTC"
    assert captured["params"]["mode"] == "historical"
    assert captured["params"]["from"] == "2026-10-01"
    assert captured["params"]["to"] == "2026-10-10"
    assert captured["headers"]["Authorization"] == "Bearer free-test-token"


def test_volume_history_skips_missing_credentials_before_network_attempt(monkeypatch):
    settings = Settings(
        marketdata_token=None,
        tradier_token=None,
        option_history_provider_order="marketdata,tradier",
    )
    fetcher = DataFetcher(settings)

    def unexpected(*args, **kwargs):
        raise AssertionError("no provider adapter should run without credentials")

    monkeypatch.setattr(fetcher, "_attempt", unexpected)
    with pytest.raises(DataUnavailableError) as exc:
        fetcher.fetch_option_volume_history(
            "ABC261120C00100000",
            start=datetime.now(timezone.utc) - timedelta(days=14),
            end=datetime.now(timezone.utc),
        )
    attempts = exc.value.attempts
    assert [item.provider for item in attempts] == ["marketdata", "tradier"]
    assert all("not configured" in str(item.error) for item in attempts)


def test_legacy_price_history_missing_tradier_fails_quietly_before_adapter(monkeypatch):
    settings = Settings(tradier_token=None)
    fetcher = DataFetcher(settings)

    def unexpected(*args, **kwargs):
        raise AssertionError("missing Tradier must not generate adapter warning calls")

    monkeypatch.setattr(fetcher, "_attempt", unexpected)
    with pytest.raises(DataUnavailableError) as exc:
        fetcher.fetch_option_history(
            "ABC261120C00100000",
            start=datetime.now(timezone.utc) - timedelta(days=14),
            end=datetime.now(timezone.utc),
            interval="1d",
        )
    assert len(exc.value.attempts) == 1
    assert exc.value.attempts[0].provider == "tradier"
    assert "skipped" in str(exc.value.attempts[0].error)


def test_scanner_enables_anomaly_history_when_marketdata_free_token_exists():
    radar = OptionsRadar.__new__(OptionsRadar)
    radar.settings = Settings(
        marketdata_token="free-test-token",
        tradier_token=None,
    )
    assert radar._option_history_available() is True

    radar.settings = Settings(
        marketdata_token=None,
        tradier_token=None,
    )
    assert radar._option_history_available() is False
