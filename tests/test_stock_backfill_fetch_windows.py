"""Regression: historical Yahoo 5m limit must not poison recent signal audits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.stock_audit_rotation import apply_symbol_bars_fair
from scripts.run_stock_outcome_audit import _symbol_window

NOW = datetime(2026, 10, 19, 22, tzinfo=timezone.utc)


def row(*, age: timedelta, status: str = "pending",
        covered_60m: bool = False) -> dict:
    return {
        "symbol": "RGC",
        "signal_time": (NOW - age).isoformat(),
        "signal_session_valid": True,
        "audit_status": status,
        "coverage": {"15m": covered_60m, "60m": covered_60m, "1d": False},
        "direction": "up",
        "entry_price": 100.0,
        "follow_through_target_pct": 6,
        "failure_threshold_pct": 6,
    }


def test_old_90d_event_does_not_expand_query_for_recent_same_symbol():
    active = row(age=timedelta(days=3))
    stale = row(age=timedelta(days=90), status="unavailable")
    completed = row(age=timedelta(days=30), status="success",
                    covered_60m=True)
    audit = {"records": {"stale": stale, "completed": completed,
                         "active": active}}
    result = _symbol_window(audit, "RGC", NOW)
    assert result is not None
    assert result[0] == NOW - timedelta(days=3, minutes=5)
    assert result[1] == NOW
    assert result[0] > NOW - timedelta(days=58)


def test_no_provider_calls_for_expired_or_immutable_terminal_signal():
    expired = row(age=timedelta(days=90))
    finalized = row(age=timedelta(days=2), status="failed")
    audit = {"records": {"expired": expired, "finalized": finalized}}
    assert _symbol_window(audit, "RGC", NOW) is None
    assert _symbol_window(audit, "OTHER", NOW) is None
    audit["records"]["expired"]["signal_session_valid"] = False
    assert _symbol_window(audit, "RGC", NOW) is None


def test_newer_replay_cannot_erase_previously_verified_60m_checkpoint():
    covered = row(age=timedelta(days=2), covered_60m=True)
    covered.update({
        "signal_id": "verified",
        "audit_source": "yahoo/yfinance historical 5m research fallback",
        "audited_at": (NOW - timedelta(days=1)).isoformat(),
        "checkpoints": {
            "60m": {
                "observed_at": (NOW - timedelta(days=2) + timedelta(hours=1)).isoformat(),
                "coverage_qualified": True,
            }
        },
    })
    baseline = dict(covered)
    audit = {"records": {"verified": covered}}
    # Retention-limited empty replay is NOT proof that past checkpoint vanished.
    updated = apply_symbol_bars_fair(
        audit, symbol="RGC", bars=pd.DataFrame(), now=NOW,
        source="yahoo retry returned no bars",
    )
    assert updated == 0
    result = audit["records"]["verified"]
    assert result["coverage"]["60m"] is True
    assert result["checkpoints"] == baseline["checkpoints"]
    assert result["audit_status"] == "pending"
    assert result["audit_recovery_state"] == "preserved_prior_verified_checkpoint"


def test_terminal_result_is_never_recomputed_or_demoted_even_without_1d():
    completed = row(age=timedelta(days=2), status="success",
                    covered_60m=True)
    completed["audit_reason"] = "target_touched_first_in_observed_5m_sequence"
    audit = {"records": {"completed": completed}}
    updated = apply_symbol_bars_fair(
        audit, symbol="RGC", bars=pd.DataFrame(), now=NOW, source="empty",
    )
    assert updated == 0
    assert audit["records"]["completed"]["audit_status"] == "success"
    assert audit["records"]["completed"]["audit_reason"] == (
        "target_touched_first_in_observed_5m_sequence"
    )


def test_unfinished_recent_signals_wait_for_completed_bar():
    active = row(age=timedelta(minutes=10))
    assert _symbol_window({"records": {"recent": active}}, "RGC", NOW) is None
