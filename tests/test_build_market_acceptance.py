"""Market recovery must follow completed production evidence, not CI green lights."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.build_market_acceptance import evaluate

NOW = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)


def _reports(*, ready: bool = True):
    at = NOW.isoformat()
    return {
        "daily_plan": {
            "schema": "ghazi.daily_plan_sheet.v1", "generated_at": at,
            "private_mode": {"enabled": ready, "reason": "OWNER_AUTHORIZED_INTERNAL_USE"
                             if ready else "DATA_USE_PERMISSION_REQUIRED", "delivery": "NOT_ATTEMPTED"},
            "analysis_funnel": {"bars_fetched": {"count": 3 if ready else 0},
                                "analysed": {"count": 2 if ready else 0}},
            "readiness": {"multi_timeframe": {"private_owner": "FULL" if ready else "UNAVAILABLE"},
                          "price_levels": {"private_owner": "COMPUTED" if ready else "NOT_COMPUTED"}},
        },
        "operations": {"generated_at": at, "status": "degraded"},
        "scorecards": {"schema": "ghazi.platform_scorecards.v1", "generated_at": at,
                       "scorecards": {"TELEGRAM_DELIVERY": {"status": "DELIVERED"},
                                      "SIGNAL_PERFORMANCE": {"status": "NO_PROVEN_EDGE"}}},
        "trading_readiness": {"schema": "ghazi.trading_readiness.v1", "generated_at": at,
                              "checks": {"walk_forward_passed": False, "stock_edge_proven": False,
                                         "options_execution_sources": False}},
    }


def test_operations_and_news_telegram_cannot_qualify_market_signals():
    reports = _reports(ready=False)
    result = evaluate(reports, now=NOW)
    checks = result["checks"]
    assert checks["operational_telegram_digest_accepted"]
    assert not checks["private_market_report_telegram_accepted"]
    assert not checks["private_bars_observed"]
    assert not checks["private_multi_frame_levels_computed"]
    assert not checks["out_of_sample_trading_edge_proven"]
    assert result["status"] == "RESEARCH_EVIDENCE_PENDING"
    assert [s["id"] for s in result["action_queue"]][:2] == [
        "REVIEW_SOURCE_RIGHTS", "MEASURE_SUPPORT_AND_TRENDS"]


def test_private_bar_coverage_is_distinct_from_empirical_and_delivery_proof():
    reports = _reports()
    result = evaluate(reports, now=NOW)
    assert result["checks"]["private_bars_observed"] is True
    assert result["checks"]["private_multi_frame_levels_computed"] is True
    assert result["checks"]["private_market_report_telegram_accepted"] is False
    assert result["checks"]["out_of_sample_trading_edge_proven"] is False
    assert result["counts"] == {"price_bar_symbols_fetched": 3, "symbols_with_computed_levels": 2}
    # Even when every research proof exists, never assert brokerage authorization.
    reports["daily_plan"]["private_mode"]["delivery"] = "DELIVERED"
    reports["scorecards"]["scorecards"]["SIGNAL_PERFORMANCE"]["status"] = "EDGE_PROVEN"
    reports["trading_readiness"]["checks"].update({"walk_forward_passed": True, "stock_edge_proven": True})
    yes = evaluate(reports, now=NOW)
    assert yes["status"] == "RESEARCH_EVIDENCE_REPORTED"
    assert yes["checks"]["private_market_report_telegram_accepted"]
    assert yes["checks"]["out_of_sample_trading_edge_proven"]
    assert yes["execution_authority"] is False
    assert yes["signal_success_probability"] is None
    assert yes["checks"]["execution_grade_option_quotes_verified"] is False


def test_stale_or_future_generated_data_fail_closed():
    reports = _reports()
    reports["daily_plan"]["generated_at"] = (NOW - timedelta(hours=40)).isoformat()
    stale = evaluate(reports, now=NOW)
    assert stale["counts"]["price_bar_symbols_fetched"] == 0
    assert not stale["checks"]["private_bars_observed"]
    assert not stale["checks"]["private_multi_frame_levels_computed"]
    reports["daily_plan"]["generated_at"] = (NOW + timedelta(hours=1)).isoformat()
    assert not evaluate(reports, now=NOW)["checks"]["private_bars_observed"]


def test_wrong_schema_malformed_counts_and_error_status_never_upgrade():
    reports = _reports()
    reports["daily_plan"]["analysis_funnel"]["bars_fetched"]["count"] = True
    reports["daily_plan"]["analysis_funnel"]["analysed"]["count"] = "-7"
    result = evaluate(reports, now=NOW)
    assert result["counts"] == {"price_bar_symbols_fetched": 0, "symbols_with_computed_levels": 0}
    assert not result["checks"]["private_multi_frame_levels_computed"]
    reports["daily_plan"]["schema"] = "wrong.schema"
    assert not evaluate(reports, now=NOW)["checks"]["private_bars_observed"]
    with pytest.raises(ValueError):
        evaluate(reports, now=NOW.replace(tzinfo=None))


def test_report_public_surface_never_contains_private_symbols_prices_or_tokens():
    reports = _reports()
    reports["daily_plan"]["private_mode"]["symbols"] = ["NVDA", "PRIVATE"]
    reports["daily_plan"]["secret_key"] = "SHOULD_NOT_LEAK"
    reports["daily_plan"]["private_plans"] = {"SPY": {"entry": 534.22}}
    report = evaluate(reports, now=NOW)
    content = json.dumps(report, ensure_ascii=False)
    for token in ("SHOULD_NOT_LEAK", "PRIVATE", "NVDA", "SPY", "534.22"):
        assert token not in content
    assert report["public_market_prices"] is None
    assert report["research_only"]
