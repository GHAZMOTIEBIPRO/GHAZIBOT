from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from options_radar.provider_preflight import (
    _annotate,
    configured_providers,
    normalize_provider_list,
    provider_is_configured,
)


def _settings(**overrides):
    values = {
        "tradier_token": None,
        "marketdata_token": None,
        "finnhub_api_key": None,
        "tiingo_api_key": None,
        "alpaca_api_key": None,
        "alpaca_secret_key": None,
        "twelve_data_api_key": None,
        "polygon_api_key": None,
        "alpha_vantage_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_unconfigured_paid_or_account_providers_are_pruned_but_yahoo_remains() -> None:
    configured, skipped = configured_providers(
        _settings(),
        [
            "tradier",
            "alpaca",
            "tiingo",
            "finnhub",
            "twelve_data",
            "polygon",
            "alpha_vantage",
            "marketdata",
            "yahoo",
        ],
    )
    assert configured == ["yahoo"]
    assert skipped == [
        "tradier",
        "alpaca",
        "tiingo",
        "finnhub",
        "twelve_data",
        "polygon",
        "alpha_vantage",
        "marketdata",
    ]


def test_configured_providers_keep_original_order() -> None:
    settings = _settings(
        tradier_token="configured",
        finnhub_api_key="configured",
        alpaca_api_key="configured",
        alpaca_secret_key="configured",
    )
    configured, skipped = configured_providers(
        settings,
        ["tradier", "alpaca", "finnhub", "yahoo"],
    )
    assert configured == ["tradier", "alpaca", "finnhub", "yahoo"]
    assert skipped == []


def test_alpaca_requires_both_key_and_secret() -> None:
    assert provider_is_configured(_settings(alpaca_api_key="configured"), "alpaca") is False
    assert provider_is_configured(
        _settings(alpaca_api_key="configured", alpaca_secret_key="configured"),
        "alpaca",
    ) is True


def test_aliases_normalize_without_duplicates_and_unknown_provider_is_preserved() -> None:
    assert normalize_provider_list("twelve,twelvedata,yfinance,alpha,custom") == [
        "twelve_data",
        "yahoo",
        "alpha_vantage",
        "custom",
    ]
    assert provider_is_configured(_settings(), "custom") is True


def test_preflight_metadata_contains_no_credential_values() -> None:
    result = SimpleNamespace(metadata={})
    _annotate(result, ["yahoo"], ["tradier", "finnhub"])
    block = result.metadata["provider_preflight"]
    assert block == {
        "configured_providers": ["yahoo"],
        "skipped_unconfigured": ["tradier", "finnhub"],
        "adapter_attempts_avoided": 2,
        "credentials_exposed": False,
        "decision_authority": False,
    }


def test_fabric_entrypoints_install_preflight_before_singleflight() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/run_options_radar_fabric.py",
        "scripts/fast_explosion_scan_fabric.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "install_data_fabric()" in text
        assert "install_provider_preflight()" in text
        assert "install_data_fabric_singleflight()" in text
        assert text.index("install_data_fabric()") < text.index("install_provider_preflight()")
        assert text.index("install_provider_preflight()") < text.index("install_data_fabric_singleflight()")
