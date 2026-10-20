from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from options_radar.stock_audit_rotation import (
    fair_symbols_needing_backfill,
    mark_symbol_attempt,
    migrate_and_classify_records,
    recalculate_fair_coverage,
)

NOW = datetime(2026, 8, 17, 23, 0, tzinfo=timezone.utc)


def _row(
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    *,
    status: str = "pending",
    attempts: int | None = None,
    last_attempt: datetime | None = None,
    covered_60m: bool = False,
    covered_1d: bool = False,
    audited_at: datetime | None = None,
) -> dict:
    row = {
        "signal_id": signal_id,
        "symbol": symbol,
        "signal_time": signal_time.isoformat(),
        "direction": "up",
        "entry_price": 10.0,
        "audit_status": status,
        "decision_authority": False,
        "coverage": {"60m": covered_60m, "1d": covered_1d},
    }
    if attempts is not None:
        row["audit_attempt_count"] = attempts
    if last_attempt is not None:
        row["audit_last_attempt_at"] = last_attempt.isoformat()
    if audited_at is not None:
        row["audited_at"] = audited_at.isoformat()
    return row


def test_non_trading_day_is_quarantined_not_counted_as_loss():
    saturday = datetime(2026, 8, 15, 1, 17, tzinfo=timezone.utc)
    audit = {"records": {"sat": _row("sat", "SAT", saturday)}}
    migrate_and_classify_records(audit)
    row = audit["records"]["sat"]
    assert row["signal_session_valid"] is False
    assert row["audit_classification"] == "invalid_session"
    assert row["audit_status"] == "unavailable"
    assert row["audit_reason"].startswith("invalid_signal_session:")

    recalculate_fair_coverage(audit)
    coverage = audit["coverage"]
    assert coverage["records_total"] == 1
    assert coverage["records"] == 0
    assert coverage["invalid_session"] == 1
    assert coverage["decisive"] == 0
    assert audit["invalid_session_policy"]["deleted"] is False


def test_valid_extended_session_remains_performance_eligible():
    premarket = datetime(2026, 8, 13, 13, 6, tzinfo=timezone.utc)
    audit = {"records": {"ok": _row("ok", "OK", premarket)}}
    migrate_and_classify_records(audit)
    assert audit["records"]["ok"]["signal_session_valid"] is True
    recalculate_fair_coverage(audit)
    assert audit["coverage"]["records"] == 1
    assert audit["coverage"]["invalid_session"] == 0


def test_never_attempted_symbols_are_prioritized_over_retries():
    base = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    audit = {
        "records": {
            "retry": _row(
                "retry",
                "AAA",
                base,
                attempts=2,
                last_attempt=NOW - timedelta(hours=30),
            ),
            "fresh2": _row("fresh2", "CCC", base + timedelta(minutes=2), attempts=0),
            "fresh1": _row("fresh1", "BBB", base + timedelta(minutes=1), attempts=0),
        }
    }
    migrate_and_classify_records(audit)
    symbols = fair_symbols_needing_backfill(audit, now=NOW, maximum_symbols=2)
    assert symbols == ["BBB", "CCC"]


def test_terminal_event_leaves_queue_without_one_day_checkpoint():
    event_time = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    audit = {
        "records": {
            "done": _row(
                "done",
                "DONE",
                event_time,
                status="success",
                attempts=1,
                covered_60m=True,
                covered_1d=False,
            ),
            "fresh": _row("fresh", "FRESH", event_time + timedelta(minutes=1), attempts=0),
        }
    }
    migrate_and_classify_records(audit)
    assert fair_symbols_needing_backfill(audit, now=NOW, maximum_symbols=10) == ["FRESH"]


def test_retry_cooldown_prevents_same_symbol_from_monopolizing_slots():
    event_time = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    audit = {
        "records": {
            "recent": _row(
                "recent",
                "RECENT",
                event_time,
                attempts=1,
                last_attempt=NOW - timedelta(hours=2),
            ),
            "old": _row(
                "old",
                "OLD",
                event_time + timedelta(minutes=1),
                attempts=1,
                last_attempt=NOW - timedelta(hours=24),
            ),
        }
    }
    migrate_and_classify_records(audit)
    assert fair_symbols_needing_backfill(
        audit,
        now=NOW,
        maximum_symbols=10,
        retry_cooldown_hours=18,
    ) == ["OLD"]


def test_missing_60m_retry_has_priority_over_one_day_only_retry():
    event_time = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    audit = {
        "records": {
            "one_day": _row(
                "one_day",
                "LATER",
                event_time,
                attempts=1,
                last_attempt=NOW - timedelta(hours=24),
                covered_60m=True,
            ),
            "sixty": _row(
                "sixty",
                "SIXTY",
                event_time + timedelta(minutes=1),
                attempts=1,
                last_attempt=NOW - timedelta(hours=24),
                covered_60m=False,
            ),
        }
    }
    migrate_and_classify_records(audit)
    assert fair_symbols_needing_backfill(audit, now=NOW, maximum_symbols=2) == ["SIXTY", "LATER"]


def test_legacy_attempt_metadata_is_inferred_without_resetting_history():
    event_time = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    audit = {
        "records": {
            "old": _row("old", "OLD", event_time, audited_at=NOW - timedelta(days=1)),
            "new": _row("new", "NEW", event_time + timedelta(minutes=1)),
        }
    }
    migrate_and_classify_records(audit)
    assert audit["records"]["old"]["audit_attempt_count"] == 1
    assert audit["records"]["old"]["audit_last_attempt_result"] == "legacy"
    assert audit["records"]["new"]["audit_attempt_count"] == 0
    assert audit["records"]["new"]["audit_last_attempt_result"] == "never_attempted"


def test_mark_attempt_does_not_increment_unrelated_terminal_row_same_symbol():
    event_time = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)
    terminal = _row("done", "SAME", event_time, status="success", attempts=1, covered_60m=True)
    pending = _row("pending", "SAME", event_time + timedelta(hours=1), attempts=0)
    audit = {"records": {"done": terminal, "pending": pending}}
    migrate_and_classify_records(audit)
    mark_symbol_attempt(audit, symbol="SAME", now=NOW, result="fetch_error", error="x")
    assert audit["records"]["done"]["audit_attempt_count"] == 1
    assert audit["records"]["pending"]["audit_attempt_count"] == 1
    assert audit["records"]["pending"]["audit_last_attempt_result"] == "fetch_error"


def test_workflow_uses_larger_fair_batch_but_remains_free_and_silent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/stock-outcome-auditor.yml").read_text(encoding="utf-8")
    runner = (root / "scripts/run_stock_outcome_audit.py").read_text(encoding="utf-8")
    assert 'STOCK_OUTCOME_AUDIT_MAX_SYMBOLS: "160"' in workflow
    assert 'STOCK_OUTCOME_AUDIT_RETRY_COOLDOWN_HOURS: "2"' in workflow
    assert 'PAID_MARKET_DATA_ALLOWED: "false"' in workflow
    assert "TELEGRAM" not in workflow
    assert 'providers=["yahoo"]' in runner
    assert "recoverable_recent_first_then_cooled_down_retries" in runner
    assert "terminal_events_do_not_require_1d_to_leave_queue" in runner


def test_sixty_minute_horizon_after_close_is_labelled_not_applicable_not_covered():
    # 2026-08-13 is a regular XNYS session; close 16:00 ET = 20:00 UTC.
    mid = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)        # 11:00 ET
    last_hour = datetime(2026, 8, 13, 19, 41, tzinfo=timezone.utc)  # 15:41 ET
    at_edge = datetime(2026, 8, 13, 19, 0, tzinfo=timezone.utc)     # 15:00 ET, ends at close
    after_hours = datetime(2026, 8, 13, 21, 30, tzinfo=timezone.utc)
    covered_late = datetime(2026, 8, 13, 19, 50, tzinfo=timezone.utc)
    audit = {"records": {
        "mid": _row("mid", "AAA", mid),
        "late": _row("late", "BBB", last_hour, status="success"),
        "edge": _row("edge", "CCC", at_edge),
        "after": _row("after", "DDD", after_hours, status="failed"),
        "covered": _row("covered", "EEE", covered_late, covered_60m=True),
    }}
    for row in audit["records"].values():
        row["signal_session_valid"] = True
    recalculate_fair_coverage(audit)
    rows, coverage = audit["records"], audit["coverage"]
    assert rows["late"]["coverage_60m_applicability"] == "NOT_APPLICABLE_HORIZON_AFTER_REGULAR_CLOSE"
    assert rows["after"]["coverage_60m_applicability"] == "NOT_APPLICABLE_HORIZON_AFTER_REGULAR_CLOSE"
    # Outcomes are untouched and records are never deleted.
    assert rows["late"]["audit_status"] == "success" and rows["after"]["audit_status"] == "failed"
    for key in ("mid", "edge", "covered"):
        assert "coverage_60m_applicability" not in rows[key]
    assert coverage["eligible_records"] == 5
    assert coverage["coverage_60m_not_applicable_after_close"] == 2
    assert coverage["coverage_60m_applicable_records"] == 3
    assert coverage["covered_60m"] == 1
    assert coverage["coverage_60m_pct"] == 33.33
    assert coverage["coverage_60m_all_eligible_pct"] == 20.0
    policy = audit["sixty_minute_applicability_policy"]
    assert policy["outcome_or_status_changed"] is False and policy["deleted"] is False


def test_pre_open_horizon_is_labelled_by_timestamp_only_and_outcomes_kept():
    # 2026-08-13 XNYS open 09:30 ET = 13:30 UTC.
    early = datetime(2026, 8, 13, 11, 45, tzinfo=timezone.utc)      # 07:45 ET, ends 08:45
    edge = datetime(2026, 8, 13, 12, 30, tzinfo=timezone.utc)       # 08:30 ET, ends at open
    straddle = datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc)    # 09:00 ET, ends 10:00
    covered_early = datetime(2026, 8, 13, 11, 50, tzinfo=timezone.utc)
    saturday = datetime(2026, 8, 15, 11, 45, tzinfo=timezone.utc)
    audit = {"records": {
        "early_win": _row("early_win", "AAA", early, status="success"),
        "early_loss": _row("early_loss", "BBB", early, status="failed"),
        "edge": _row("edge", "CCC", edge, status="failed"),
        "straddle": _row("straddle", "DDD", straddle),
        "covered": _row("covered", "EEE", covered_early, covered_60m=True),
        "sat": _row("sat", "FFF", saturday),
    }}
    for row in audit["records"].values():
        row["signal_session_valid"] = True
    recalculate_fair_coverage(audit)
    rows, coverage = audit["records"], audit["coverage"]
    tag = "NOT_APPLICABLE_HORIZON_BEFORE_REGULAR_OPEN"
    # Winners and losers alike: the rule never looks at the outcome.
    for key in ("early_win", "early_loss", "edge"):
        assert rows[key]["coverage_60m_applicability"] == tag
    assert rows["early_win"]["audit_status"] == "success"
    assert rows["early_loss"]["audit_status"] == "failed"
    for key in ("straddle", "covered", "sat"):
        assert "coverage_60m_applicability" not in rows[key]
    assert coverage["coverage_60m_not_applicable_before_open"] == 3
    assert coverage["coverage_60m_not_applicable_after_close"] == 0
    assert coverage["coverage_60m_not_applicable_total"] == 3
    assert coverage["coverage_60m_applicable_records"] == 3
    assert coverage["coverage_60m_pct"] == 33.33
    assert coverage["coverage_60m_pct_before_pre_open_rule"] == 16.67
    assert coverage["coverage_60m_all_eligible_pct"] == 16.67
    rule = audit["sixty_minute_applicability_policy"]["pre_open_rule"]
    assert rule["decided_by_timestamp_only"] is True and rule["deleted"] is False


def test_unparseable_or_non_session_signal_stays_in_60m_denominator():
    saturday = datetime(2026, 8, 15, 19, 50, tzinfo=timezone.utc)
    broken = _row("broken", "AAA", saturday)
    broken["signal_time"] = "not-a-time"
    audit = {"records": {"sat": _row("sat", "BBB", saturday), "broken": broken}}
    for row in audit["records"].values():
        row["signal_session_valid"] = True
    recalculate_fair_coverage(audit)
    assert audit["coverage"]["coverage_60m_not_applicable_after_close"] == 0
    assert audit["coverage"]["coverage_60m_applicable_records"] == 2
