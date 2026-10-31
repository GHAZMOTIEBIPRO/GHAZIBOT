"""Production source-network regressions (not unused legacy helpers).

A success from stock bars is never evidence of option trades/quotes.
A denied Yahoo automation gate outranks cached successful provider attempts.
"""
import json
from types import SimpleNamespace

from options_radar import phase60_overlay


def _settings():
    return SimpleNamespace(
        tiingo_api_key=None, finnhub_api_key=None, tradier_token=None,
        alpaca_api_key=None, alpaca_secret_key=None,
        polygon_api_key=None, twelve_data_api_key=None,
        alpha_vantage_api_key=None, marketdata_token=None,
        alpaca_stock_feed="iex", tradier_base_url="https://sandbox.tradier.com",
    )


def _yahoo():
    return {"stocks": {"SPY": {"attempts": [
        {"provider": "yahoo", "success": True}]}},
        "options": {"SPY": {"attempts": [
            {"provider": "yfinance", "success": True}]}}}


def test_live_overlay_rejects_old_yahoo_success_in_both_source_counters(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    report = phase60_overlay.build_source_network(_settings(), {}, _yahoo())
    assert report["summary"]["active_stock_sources"] == 0
    assert report["summary"]["active_option_sources"] == 0
    for category in ("stocks", "options"):
        source = next(x for x in report[category] if x["name"] == "yahoo")
        assert source["status"] == "SOURCE_TERMS_BLOCKED"
        assert source["configured"] is False
        assert source["used_successfully"] is False


def test_stock_quote_provider_does_not_become_an_option_source(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    settings = _settings()
    settings.alpaca_api_key = "fixture"
    settings.alpaca_secret_key = "fixture"
    audit = {"stocks": {"SPY": {"attempts": [
        {"provider": "alpaca", "success": True}]}}, "options": {}}
    report = phase60_overlay.build_source_network(settings, {}, audit)
    assert report["summary"]["active_stock_sources"] == 1
    assert report["summary"]["active_option_sources"] == 0
    assert next(x for x in report["options"] if x["name"] == "alpaca")["used_successfully"] is False


def test_option_chain_does_not_become_successful_stock_source(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    settings = _settings()
    settings.tradier_token = "fixture"
    audit = {"stocks": {}, "options": {"SPY": {"attempts": [
        {"provider": "tradier", "success": True}]}}}
    report = phase60_overlay.build_source_network(settings, {}, audit)
    assert report["summary"]["active_stock_sources"] == 0
    assert report["summary"]["active_option_sources"] == 1


def test_nonintegrated_opra_placeholder_does_not_get_fake_success(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    settings = _settings()
    settings.polygon_api_key = "fixture"
    report = phase60_overlay.build_source_network(settings, {}, {
        "stocks": {}, "options": {"SPY": {"attempts": [
            {"provider": "polygon_options", "success": True}]}}})
    option = next(x for x in report["options"] if x["name"] == "polygon_options")
    assert option["status"] == "entitlement_required"
    assert option["used_successfully"] is False
    assert report["summary"]["active_option_sources"] == 0


def test_apply_phase60_overlay_writes_correct_network_into_export(monkeypatch, tmp_path):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    p = tmp_path / "audit.json"
    p.write_text(json.dumps(_yahoo()))
    monkeypatch.setattr(phase60_overlay, "SOURCE_AUDIT_PATH", p)
    payload = {"stocks": [], "options": [], "top_calls": [], "top_puts": [],
               "summary": {}}
    result = phase60_overlay.apply_phase60_overlay(payload, _settings())
    assert result["source_network"]["summary"]["active_option_sources"] == 0
    assert result["source_network"]["summary"]["active_stock_sources"] == 0
