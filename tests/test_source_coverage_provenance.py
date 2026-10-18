from __future__ import annotations

from options_radar.provider_readiness import assess_provider_readiness
from options_radar.source_coverage import coverage_diagnostics
from options_radar.omega_observability import build_data_status


def test_same_upstream_aliases_never_count_as_cross_source() -> None:
    audit = {"SPY": {
        "source": "fabric:yahoo+yfinance",
        "attempts": [
            {"provider": "yahoo", "success": True},
            {"provider": "yfinance", "success": True},
        ],
        "metadata": {"data_fabric": {}},
    }}
    check = assess_provider_readiness(audit).as_dict()
    assert check["cross_source_chains"] == 0
    assert check["fallback_only_chains"] == 1
    assert check["production_quote_ready"] is False
    assert check["production_flow_ready"] is False


def test_polygon_and_massive_one_family_not_quote_entitlement() -> None:
    audit = {"SPY": {
        "source": "fabric:polygon+massive",
        "attempts": [
            {"provider": "polygon", "success": True},
            {"provider": "massive", "success": True},
        ],
        "metadata": {"data_fabric": {}},
    }}
    check = assess_provider_readiness(audit).as_dict()
    assert check["cross_source_chains"] == 0
    assert check["production_quote_ready"] is False


def test_price_vs_official_context_is_explicit() -> None:
    network = {"stocks": [
        {"name": "SEC EDGAR", "active": True, "official": True},
        {"name": "openFDA / Drugs@FDA", "active": True, "official": True},
        {"name": "Yahoo/yfinance", "active": True},
        {"name": "Tiingo", "active": False},
    ]}
    readiness = {
        "sources": ["yahoo"],
        "fallback_only_chains": 13,
        "live_primary_chains": 0,
        "cross_source_chains": 0,
        "production_quote_ready": False,
        "production_flow_ready": False,
    }
    report = coverage_diagnostics(network, readiness)
    assert report["stock_price_source_families_reported"] == ["yahoo"]
    assert "SEC EDGAR" in report["stock_non_price_context_sources_reported"]
    assert report["stock_primary_non_yahoo_families_reported"] == []
    assert report["option_chain_source_families"] == ["yahoo"]
    assert "NO_EXECUTION_GRADE_OPTION_QUOTE" in report["blocking_codes"]
    assert "NO_INDEPENDENT_CROSS_SOURCE_CHAIN" in report["blocking_codes"]


def test_missing_source_does_not_become_live() -> None:
    report = coverage_diagnostics(None, None)
    assert report["stock_price_source_families_reported"] == []
    assert report["options_execution_quote_ready"] is False
    assert report["options_trade_flow_ready"] is False
    assert "NO_VERIFIED_OPTION_PROVIDER_FAMILY" in report["blocking_codes"]


def test_coverage_published_as_non_decision_metadata() -> None:
    payload = {
        "generated_at": "2026-10-18T14:00:00+00:00",
        "source_network": {"summary": {"active_stock_sources": 2},
                           "stocks": [{"name": "Yahoo/yfinance", "active": True}]},
        "provider_audit": {"SPY": {
            "source": "yahoo",
            "freshness": "unofficial / may be delayed",
            "attempts": [{"provider": "yahoo", "success": True}],
        }},
        "options": [],
        "stocks": [],
    }
    status = build_data_status(payload)
    assert status["source_status"]["active_stock_sources"] == 2
    assert status["coverage_diagnostics"]["stock_price_source_families_reported"] == ["yahoo"]
    assert status["option_provider_readiness"]["production_quote_ready"] is False
    assert status["row_counts"]["options"] == 0


def test_public_diagnostics_never_exposes_token_values() -> None:
    readiness = {"sources": ["yahoo"], "production_quote_ready": False}
    report = coverage_diagnostics({"stocks": [{"name": "SEC EDGAR", "active": True}]}, readiness)
    assert not any("token" in key or "secret" in key for key in report)
