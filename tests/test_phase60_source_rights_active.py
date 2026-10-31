"""Source usage success never overrides source licensing/terms restrictions."""
from types import SimpleNamespace

from options_radar.phase60_source_network import build_source_network


def fake_settings():
    return SimpleNamespace(
        tiingo_api_key=None, finnhub_api_key=None, tradier_token=None,
        alpaca_api_key=None, alpaca_secret_key=None,
        polygon_api_key=None, twelve_data_api_key=None,
        alpha_vantage_api_key=None, marketdata_token=None,
        alpaca_stock_feed="iex", tradier_base_url="https://sandbox.tradier.com",
    )


def test_yahoo_denial_wins_over_provider_success_and_old_cache(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    audit = {
        "stocks": {"SPY": {"attempts": [{"provider": "yahoo", "success": True}]}},
        "options": {"SPY": {"attempts": [{"provider": "yahoo", "success": True}]}},
    }
    report = build_source_network(fake_settings(), {}, audit)
    assert report["summary"]["active_stock_sources"] == 0
    assert report["summary"]["active_option_sources"] == 0
    stock = next(r for r in report["stocks"] if r["name"] == "yahoo")
    option = next(r for r in report["options"] if r["name"] == "yahoo")
    assert stock["status"] == "SOURCE_TERMS_BLOCKED"
    assert option["status"] == "SOURCE_TERMS_BLOCKED"
    assert stock["used_successfully"] is False
    assert option["used_successfully"] is False
    assert stock["configured"] is False and option["configured"] is False


def test_other_provider_success_remains_separate_without_yahoo(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    audit = {"stocks": {"SPY": {
        "attempts": [{"provider": "twelve_data", "success": True}]}},
        "options": {}}
    settings = fake_settings()
    settings.twelve_data_api_key = "mocked_account_key"
    result = build_source_network(settings, {}, audit)
    assert result["summary"]["active_stock_sources"] == 1
    assert result["summary"]["active_option_sources"] == 0
    assert next(r for r in result["stocks"] if r["name"] == "twelve_data")["used_successfully"] is True
