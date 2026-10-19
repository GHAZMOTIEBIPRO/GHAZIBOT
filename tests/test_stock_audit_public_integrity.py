"""Public sample-integrity cannot be upgraded just because code was patched."""
from datetime import datetime, timezone
from pathlib import Path

from scripts.publish_stock_audit_summary import build_summary

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def report(records):
    return {
        "mode": "HISTORICAL_5M_OUTCOME_AUDIT",
        "decision_authority": False,
        "coverage": {
            "records": 3, "records_total": 3, "eligible_records": 3,
            "covered_60m": 2, "decisive": 2, "pending": 1,
        },
        "promotion_gate": {
            "coverage_ready": False,
            "minimum_independent_sessions": 10,
            "minimum_60m_coverage_pct": 90,
            "live_promotion_allowed": False,
        },
        "records": records,
    }


def test_only_evaluated_v2_completed_candles_are_verified():
    original = {"signal_session_valid": True, "audit_status": "success"}
    versioned = {
        "signal_session_valid": True, "audit_status": "failed",
        "measurement_policy": {
            "measurement_version": 2,
            "bar_completion_enforced_as_of": True,
        },
    }
    result = build_summary(report({
        "a": original,
        "b": versioned,
        "c": {"audit_status": "pending"},
    }), now=NOW)
    assert result["coverage"]["records"] == 3
    assert result["close_time_integrity"]["verified_version_2_records"] == 1
    assert result["close_time_integrity"]["legacy_or_unreverified_records"] == 2
    assert result["proven_edge"] is False
    assert result["verified_win_rate_pct"] is None
    assert result["promotion_gate"]["live_promotion_allowed"] is False


def test_legacy_archive_is_not_silently_reinterpreted_as_rechecked():
    result=build_summary(report({"a":{"audit_status":"success"}}),now=NOW)
    assert result["close_time_integrity"]["verified_version_2_records"] == 0
    assert result["close_time_integrity"]["historical_legacy_not_reclassified_as_verified"]


def test_public_trust_tab_discloses_60m_coverage_and_legacy_vs_rechecked():
    js = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert "stock_audit_public.json" in js
    assert 'String(audit.coverage' not in js
    assert "close_time_integrity" in js
    assert "coveragePct" in js
    assert "معدل نجاح مثبت: غير متاح" in js
    assert "audit?.promotion_gate?.coverage_ready===true" in js
