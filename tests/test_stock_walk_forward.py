from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

from options_radar.stock_walk_forward import run_stock_walk_forward


def _audit(*, sessions: int = 12, rows_per_session: int = 12) -> dict:
    records = {}
    start = date(2026, 7, 1)
    for session_index in range(sessions):
        session = (start + timedelta(days=session_index)).isoformat()
        for row_index in range(rows_per_session):
            score = 68.0 + row_index * 2.2
            success = row_index >= 4
            signal_id = f"s{session_index:02d}-{row_index:02d}"
            records[signal_id] = {
                "signal_id": signal_id,
                "signal_time": f"{session}T15:00:00+00:00",
                "signal_session_valid": True,
                "signal_session_date": session,
                "symbol": f"T{row_index:02d}",
                "entry_score": score,
                "entry_score_band": "90-100" if score >= 90 else "80-89" if score >= 80 else "72-79" if score >= 72 else "65-71",
                "entry_stage": "EXPLOSION" if row_index >= 6 else "IGNITION",
                "market_regime": "risk_on",
                "cause_tier": "A_OFFICIAL" if row_index >= 8 else "unknown",
                "audit_status": "success" if success else "failed",
                "coverage": {"60m": True},
                "checkpoints": {
                    "60m": {
                        "coverage_qualified": True,
                        "directional_return_pct": 8.0 if success else -6.0,
                    }
                },
            }
    return {
        "mode": "HISTORICAL_5M_OUTCOME_AUDIT",
        "decision_authority": False,
        "records": records,
        "coverage": {
            "coverage_60m_pct": 100.0,
            "independent_60m_sessions": sessions,
        },
        "promotion_gate": {"coverage_ready": sessions >= 10},
    }


def test_walk_forward_fails_closed_before_coverage_gate() -> None:
    audit = _audit(sessions=3)
    audit["coverage"]["coverage_60m_pct"] = 38.41
    audit["promotion_gate"]["coverage_ready"] = False

    report = run_stock_walk_forward(audit)

    assert report["status"] == "NOT_READY"
    assert report["gate"]["ready"] is False
    assert report["research_passed"] is False
    assert report["live_promotion_allowed"] is False
    assert report["folds"] == []


def test_walk_forward_uses_prior_sessions_only_and_never_enables_live() -> None:
    report = run_stock_walk_forward(_audit())

    assert report["gate"]["ready"] is True
    assert report["status"] in {"PASSED_RESEARCH_GATE", "FAILED_RESEARCH_GATE"}
    assert report["metrics"]["oos_sessions"] >= 4
    assert report["metrics"]["oos_records"] >= 40
    assert report["data_policy"]["random_split_allowed"] is False
    assert report["data_policy"]["future_session_training_allowed"] is False
    assert report["live_promotion_allowed"] is False

    for fold in report["folds"]:
        assert fold["test_session"] not in fold["train_sessions"]
        assert all(session < fold["test_session"] for session in fold["train_sessions"])


def test_future_outcome_changes_cannot_rewrite_earlier_fold() -> None:
    original = _audit()
    changed_future = deepcopy(original)
    last_session = max(row["signal_session_date"] for row in changed_future["records"].values())
    for row in changed_future["records"].values():
        if row["signal_session_date"] == last_session:
            row["audit_status"] = "failed" if row["audit_status"] == "success" else "success"

    first_report = run_stock_walk_forward(original)
    second_report = run_stock_walk_forward(changed_future)

    earlier_first = [fold for fold in first_report["folds"] if fold["test_session"] < last_session]
    earlier_second = [fold for fold in second_report["folds"] if fold["test_session"] < last_session]
    assert earlier_first == earlier_second


def test_walk_forward_keeps_unqualified_or_invalid_rows_out_of_binary_metrics() -> None:
    audit = _audit()
    audit["records"]["invalid"] = {
        "signal_id": "invalid",
        "signal_time": "2026-07-01T15:00:00+00:00",
        "signal_session_valid": False,
        "signal_session_date": "2026-07-01",
        "entry_score": 100.0,
        "audit_status": "success",
        "coverage": {"60m": True},
        "checkpoints": {"60m": {"coverage_qualified": True, "directional_return_pct": 99.0}},
    }
    audit["records"]["unqualified"] = {
        "signal_id": "unqualified",
        "signal_time": "2026-07-01T15:00:00+00:00",
        "signal_session_valid": True,
        "signal_session_date": "2026-07-01",
        "entry_score": 100.0,
        "audit_status": "success",
        "coverage": {"60m": False},
        "checkpoints": {"60m": {"coverage_qualified": False, "directional_return_pct": 99.0}},
    }

    report = run_stock_walk_forward(audit)

    expected = 12 * 12
    assert report["metrics"]["eligible_decisive_records"] == expected
