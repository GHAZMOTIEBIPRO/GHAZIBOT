"""Production source-count truth across both overlay generations and helpers."""
from types import SimpleNamespace

from options_radar import phase60_overlay, phase61_overlay, phase60_source_network


def settings():
    return SimpleNamespace(
        tiingo_api_key=None, finnhub_api_key=None, tradier_token=None,
        alpaca_api_key=None, alpaca_secret_key=None,
        polygon_api_key=None, twelve_data_api_key=None,
        alpha_vantage_api_key=None, marketdata_token=None,
        alpaca_stock_feed="iex",
        tradier_base_url="https://sandbox.tradier.com",
    )


def audit_with_stale_success():
    return {"stocks": {"SPY": {"attempts": [
                {"provider": "yahoo", "success": True},
                {"provider": "twelve_data", "success": True},
                {"provider": "openfda", "success": True},
            ]}},
            "options": {"SPY": {"attempts": [
                {"provider": "yahoo", "success": True},
                {"provider": "tradier", "success": True},
                {"provider": "polygon_options", "success": True},
                {"provider": "alpha_vantage_options", "success": True},
            ]}}}


def test_live_export_no_key_or_denied_terms_cannot_count_historical_success(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    report = phase60_overlay.build_source_network(
        settings(), {"operational_status": {"sec_fulltext_status": {
            "available": False}}}, audit_with_stale_success())
    assert report["summary"]["active_stock_sources"] == 0
    assert report["summary"]["active_option_sources"] == 0
    assert report["summary"]["configured_stock_sources"] == 0
    assert report["summary"]["configured_option_sources"] == 0
    assert report["summary"]["active_official_event_sources"] == 1
    assert report["summary"]["configured_official_event_sources"] == 2
    assert next(x for x in report["options"] if x["name"] == "yahoo")["status"] == "SOURCE_TERMS_BLOCKED"
    assert all(not row["used_successfully"] for row in report["options"])


def test_current_stock_and_option_keys_count_only_respective_price_adapters(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    s = settings()
    s.twelve_data_api_key = "mock"
    s.tradier_token = "mock"
    a = audit_with_stale_success()
    live = phase60_overlay.build_source_network(s, {}, a)
    secondary = phase60_source_network.build_source_network(s, {}, a)
    for report in (live, secondary):
        assert report["summary"]["active_stock_sources"] == 1
        assert report["summary"]["active_option_sources"] == 1
        # Tradier is configured for stock quotes as well as options, but did not
        # successfully return a stock bar in this fixture.
        assert report["summary"]["configured_stock_sources"] == 2
        assert report["summary"]["configured_option_sources"] == 1
    assert live["summary"]["active_official_event_sources"] == 1


def test_phase61_context_and_flow_are_not_quote_feeds(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    payload = {"source_network": phase60_overlay.build_source_network(
        settings(), {}, audit_with_stale_success())}
    phase61_overlay._extend_network(payload, {
        "audit": [
            {"provider": "finra_reg_sho", "configured": True,
             "success": True, "records": 30},
            {"provider": "benzinga_option_activity", "configured": True,
             "success": True, "records": 11},
            {"provider": "alpaca_stock_snapshots", "configured": False,
             "success": True, "records": 99},
            {"provider": "alpaca_option_snapshots", "configured": False,
             "success": True, "records": 99},
        ]
    })
    summary = payload["source_network"]["summary"]
    assert summary["active_stock_sources"] == 0
    assert summary["active_option_sources"] == 0
    assert summary["active_official_event_sources"] == 2  # OpenFDA and FINRA
    assert summary["active_option_flow_context_sources"] == 1
    options = payload["source_network"]["options"]
    alpaca = next(x for x in options if x["name"] == "alpaca_option_snapshots")
    assert alpaca["used_successfully"] is False
    assert alpaca["status"] == "needs_key"


def test_nonboolean_adapter_success_is_not_evidence(monkeypatch):
    monkeypatch.delenv("YAHOO_AUTOMATED_ACCESS_APPROVED", raising=False)
    a = {"stocks": {"SPY": {"attempts": [{
        "provider": "twelve_data", "success": "true"}]}},
        "options": {}}
    s = settings()
    s.twelve_data_api_key = "mock"
    for build in (phase60_overlay.build_source_network,
                  phase60_source_network.build_source_network):
        assert build(s, {}, a)["summary"]["active_stock_sources"] == 0
    assert phase61_overlay._network_entry(
        "alpaca_stock_snapshots", "stocks", "IEX research", {
            "configured": True, "success": "true"})["used_successfully"] is False


def test_owner_gated_yahoo_success_does_not_imply_option_execution(monkeypatch):
    monkeypatch.setenv("YAHOO_AUTOMATED_ACCESS_APPROVED", "true")
    audit = {"stocks": {"SPY": {"attempts": [{"provider": "yahoo", "success": True}]}},
             "options": {"SPY": {"attempts": [{"provider": "yahoo", "success": True}]}}}
    result = phase60_overlay.build_source_network(settings(), {}, audit)
    assert result["summary"]["active_option_sources"] == 1
    assert result["policy"]["strong_recommendation_min_independent_sources"] == 2
    yahoo = next(x for x in result["options"] if x["name"] == "yahoo")
    assert "لا يثبت" in yahoo["freshness"] or "لا يثبت" in yahoo["note"]
