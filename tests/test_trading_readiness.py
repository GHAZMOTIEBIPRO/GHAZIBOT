"""Trade-readiness verdict never converts historical samples into order signals."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts.build_trading_readiness import build, load, recent, stamp

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
T = NOW.isoformat()


def fixture():
    return {
        "agreement": {
            "schema": "ghazi.source_consensus_status.v1",
            "generated_at": T, "source_charts_available": False,
            "independent_price_comparison": "NOT_VERIFIED",
            "option_bid_ask_verified": False,
        },
        "charts": {"schema": "ghazi.stock_charts.v1", "generated_at": T,
                   "status": "SOURCE_TERMS_BLOCKED", "symbols": {}, "execution_authority": False},
        "operations": {"generated_at": T, "status": "degraded",
                       "coverage_diagnostics": {"options_execution_quote_ready": False,
                                                "options_trade_flow_ready": False}},
        "access": {"schema": "ghazi.production_access.v1", "generated_at": T,
                   "site_http_accessible": True, "bot_api_authenticated": True},
        "audit": {"schema": "ghazi.public_stock_outcomes.v1", "generated_at": T,
                  "coverage": {"records": 714},
                  "close_time_integrity": {"verified_version_2_records": 58},
                  "promotion_gate": {"live_promotion_allowed": False},
                  "proven_edge": False, "verified_win_rate_pct": None},
        "walk": {"mode": "EXPANDING_SESSION_WALK_FORWARD",
                 "gate": {"ready": True}, "research_passed": False,
                 "live_promotion_allowed": False},
        "targets": {"schema_version": 1, "generated_at": T,
                    "global_matured_t1_sample": 412, "calibration_ready": True,
                    "cohorts": {"T1:INTRADAY_1D": {"sample": 412, "hits": 8}}},
        "options": {"schema_version": 1, "generated_at": T,
                    "counts": {"closed": 0},
                    "calibration": {"active": False, "training_sample_size": 0}},
        "stages": {"schema": "ghazi.explosion_stage_evaluation.v1", "generated_at": T,
                   "research_only": True, "decision_authority": False,
                   "stages": {"PRESSURE_BUILDING": {"decisive": 306,
                                                  "expectancy_net_pct": -1.252},
                              "IGNITION": {"decisive": 20,
                                           "expectancy_net_pct": -2.385},
                              "EXPLOSION": {"decisive": 182,
                                            "expectancy_net_pct": -1.422}}},
        "strength": {"schema": "ghazi.evidence_strength.v1",
                     "generated_at": T, "score_is_prediction_win_rate": False,
                     "strength_score": 14},
    }


def test_actual_style_evidence_fails_closed_and_reports_true_sample():
    report = build(fixture(), now=NOW)
    assert report["status"] == "NOT_TRADE_READY"
    assert report["checks"]["website_and_bot"] is True
    assert report["checks"]["independent_licensed_prices"] is False
    assert report["checks"]["stock_edge_proven"] is False
    assert report["checks"]["options_execution_sources"] is False
    assert report["checks"]["walk_forward_passed"] is False
    assert report["trade_recommendations_authorized"] is False
    assert report["automated_execution_allowed"] is False
    assert report["option_v11_execution_override"] is False
    h = report["historical_evidence"]
    assert h["stock_audit_records"] == 714
    assert h["individually_close_time_verified_records"] == 58
    assert h["target_t1_intraday_hits"] == 8
    assert h["target_t1_intraday_matured"] == 412
    assert h["target_t1_historical_hit_rate_pct"] == 1.94
    assert h["historical_target_calibration_ready_reported"] is True
    assert h["qualified_option_closed_samples"] == 0
    assert h["research_data_strength_score"] == 14
    assert h["stage_cost_model_expectancy"][0]["modelled_net_expectancy_pct"] == -1.252
    assert h["historical_hit_rate_is_profit_rate"] is False
    assert h["historical_hit_rate_is_forward_probability"] is False


def test_fake_future_old_or_missing_reports_never_trust():
    f = fixture()
    f["access"]["generated_at"] = (NOW - timedelta(days=3)).isoformat()
    f["targets"]["generated_at"] = (NOW + timedelta(minutes=9)).isoformat()
    f["audit"]["generated_at"] = "2026-10-22T08:00:00"
    f["strength"]["score_is_prediction_win_rate"] = True
    f["options"]["counts"]["closed"] = "1000"
    f["stages"]["stages"]["EXPLOSION"]["expectancy_net_pct"] = float("inf")
    result = build(f, now=NOW)
    assert not result["checks"]["website_and_bot"]
    assert result["historical_evidence"]["target_t1_intraday_matured"] is None
    assert result["historical_evidence"]["stock_audit_records"] is None
    assert result["historical_evidence"]["research_data_strength_score"] is None
    assert result["historical_evidence"]["qualified_option_closed_samples"] is None
    assert result["historical_evidence"]["stage_cost_model_expectancy"][2]["modelled_net_expectancy_pct"] is None


def test_malformed_counts_and_calibration_cannot_fake_success():
    f = fixture()
    f["targets"]["cohorts"]["T1:INTRADAY_1D"] = {"sample": 12, "hits": 18}
    f["audit"]["close_time_integrity"]["verified_version_2_records"] = True
    f["audit"]["coverage"]["records"] = -3
    result = build(f, now=NOW)
    assert result["historical_evidence"]["target_t1_historical_hit_rate_pct"] is None
    assert result["historical_evidence"]["individually_close_time_verified_records"] is None
    assert result["historical_evidence"]["stock_audit_records"] is None


def test_even_perfect_claims_do_not_enable_orders_without_v11():
    f = fixture()
    f["agreement"].update({
        "source_charts_available": True, "independent_price_comparison": "VERIFIED",
        "independent_confirmations": 2, "quote_execution_eligible": True,
        "option_bid_ask_verified": True
    })
    f["charts"].update({"symbols": {"AAPL": {}}, "execution_authority": True})
    f["operations"].update({
        "status": "healthy",
        "coverage_diagnostics": {
            "options_execution_quote_ready": True,
            "options_trade_flow_ready": True, "option_live_primary_chains_reported": 200
        }
    })
    f["walk"].update({"research_passed": True, "live_promotion_allowed": True})
    f["audit"].update({"proven_edge": True, "verified_win_rate_pct": 50.0})
    f["audit"]["promotion_gate"]["live_promotion_allowed"] = True
    f["options"]["counts"]["closed"] = 150
    f["options"]["calibration"].update({"active": True, "training_sample_size": 150})
    result = build(f, now=NOW)
    assert all(result["checks"].values())
    assert result["status"] == "RESEARCH_GATES_REPORTED_READY"
    assert result["trade_recommendations_authorized"] is False
    assert result["automated_execution_allowed"] is False
    assert result["option_v11_execution_override"] is False


def test_no_naive_time_and_bounded_source_loading(tmp_path):
    assert stamp("2026-10-22T08:00:00") is None
    assert recent({"generated_at": T}, "generated_at", NOW, maximum=timedelta(hours=1))
    with pytest.raises(ValueError, match="UTC-aware"):
        build(fixture(), now=datetime(2026, 10, 22, 8))
    large = tmp_path / "large.json"
    large.write_text(" " * 210000)
    assert load(large) == {}
    invalid = tmp_path / "bad.json"
    invalid.write_text("not json")
    assert load(invalid) == {}


def test_uses_existing_single_writer_and_research_only_deployment():
    wf_text = Path(".github/workflows/site-evidence-strength.yml").read_text()
    wf = yaml.safe_load(wf_text)
    assert "GHAZI Stock Watch OHLC Charts" in wf[True]["workflow_run"]["workflows"]
    assert "scripts/build_trading_readiness.py" in wf[True]["push"]["paths"]
    assert "state/runtime/public/data/trading_readiness.json" in wf_text
    assert "git add runtime/public/data/site_strength.json" in wf_text
    assert "git push origin HEAD:bot-state" in wf_text
    assert Path("public/trading-readiness.html").is_file()
    assert "trading-readiness.js" in Path("public/trading-readiness.html").read_text()
    assert 'href="./trading-readiness.html"' in Path("public/classic.html").read_text()
