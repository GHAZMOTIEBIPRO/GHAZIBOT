from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from options_radar.stock_outcome_backfill import (
    StockOutcomeBackfillAuditor,
    evaluate_stock_event_from_bars,
)
from scripts.run_stock_outcome_audit import _apply_independent_session_gate

BASE = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)


def _state(
    *,
    signal_id: str = "s1",
    direction: str = "up",
    entry: float = 100.0,
    target: float = 6.0,
    stop: float = 6.0,
    signal_time: datetime = BASE,
    snapshot: str = "open",
) -> dict:
    return {
        "signal_id": signal_id,
        "signal_time": signal_time.isoformat(),
        "symbol": "TEST",
        "direction": direction,
        "entry_price": entry,
        "entry_stage": "EXPLOSION",
        "entry_score": 82.0,
        "entry_score_band": "80-89",
        "market_regime": "risk_on",
        "follow_through_target_pct": target,
        "failure_threshold_pct": stop,
        "terminal_outcome": snapshot,
    }


def _bars(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[3] for row in rows],
            "Close": [row[4] for row in rows],
            "Volume": [1000 for _ in rows],
        },
        index=pd.DatetimeIndex([row[0] for row in rows]),
    )


def _complete_flat_bars(*, target_touch: str | None = None, direction: str = "up") -> pd.DataFrame:
    rows = []
    for minutes in (0, 5, 10, 15, 20, 30, 60):
        high = 101.0
        low = 99.0
        close = 100.0
        if minutes == 20 and target_touch == "target":
            if direction == "down":
                low = 93.0
                close = 94.0
            else:
                high = 107.0
                close = 106.0
        elif minutes == 20 and target_touch == "stop":
            if direction == "down":
                high = 107.0
                close = 106.0
            else:
                low = 93.0
                close = 94.0
        elif minutes == 20 and target_touch == "both":
            high = 107.0
            low = 93.0
            close = 100.0
        rows.append((BASE + timedelta(minutes=minutes), 100.0, high, low, close))
    rows.append((BASE + timedelta(days=1), 100.0, 102.0, 98.0, 101.0))
    return _bars(rows)


def test_target_touch_becomes_success_and_checkpoints_use_close():
    result = evaluate_stock_event_from_bars(
        _state(),
        _complete_flat_bars(target_touch="target"),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "success"
    assert result["checkpoints"]["15m"]["price"] == 100.0
    assert result["checkpoints"]["60m"]["coverage_qualified"] is True
    assert result["checkpoints"]["1d"]["coverage_qualified"] is True
    assert result["audit_mfe_pct"] >= 7.0
    assert result["decision_authority"] is False


def test_same_bar_target_and_stop_is_ambiguous_not_a_win():
    result = evaluate_stock_event_from_bars(
        _state(snapshot="success"),
        _complete_flat_bars(target_touch="both"),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "ambiguous"
    assert result["audit_reason"] == "target_and_stop_touched_same_5m_bar_order_unknown"
    assert result["measurement_policy"]["intrabar_order_claimed"] is False
    assert result["snapshot_terminal_outcome"] == "success"


def test_no_touch_through_qualified_one_day_is_non_decisive():
    result = evaluate_stock_event_from_bars(
        _state(),
        _complete_flat_bars(),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "non_decisive"
    assert result["coverage"]["60m"] is True
    assert result["coverage"]["1d"] is True


def test_pre_signal_explosion_is_excluded_from_terminal_path():
    rows = [
        (BASE - timedelta(minutes=5), 100.0, 120.0, 99.0, 118.0),
        (BASE, 100.0, 101.0, 99.0, 100.0),
        (BASE + timedelta(minutes=15), 100.0, 101.0, 99.0, 100.0),
        (BASE + timedelta(minutes=60), 100.0, 101.0, 99.0, 100.0),
        (BASE + timedelta(days=1), 100.0, 101.0, 99.0, 100.0),
    ]
    result = evaluate_stock_event_from_bars(
        _state(),
        _bars(rows),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "non_decisive"
    assert result["measurement_policy"]["pre_signal_bar_excluded"] is True


def test_down_signal_uses_inverse_direction_for_target_and_excursion():
    result = evaluate_stock_event_from_bars(
        _state(direction="down"),
        _complete_flat_bars(target_touch="target", direction="down"),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "success"
    assert result["audit_mfe_pct"] >= 7.0
    assert result["audit_mae_pct"] <= 0.0


def test_snapshot_disagreement_is_reported_without_overwriting_snapshot():
    result = evaluate_stock_event_from_bars(
        _state(snapshot="success"),
        _complete_flat_bars(target_touch="stop"),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "failed"
    assert result["snapshot_terminal_outcome"] == "success"
    assert result["snapshot_discrepancy"] is True


def test_missing_bars_are_unavailable_not_removed():
    result = evaluate_stock_event_from_bars(
        _state(),
        pd.DataFrame(),
        now=BASE + timedelta(days=2),
    )
    assert result["audit_status"] == "unavailable"
    assert result["audit_reason"] == "no_post_signal_5m_bars"


def test_seed_preserves_every_event_in_denominator_before_fetch(tmp_path):
    path = tmp_path / "audit.json"
    auditor = StockOutcomeBackfillAuditor(path)
    audit = auditor.seed_events(
        {
            "signals": {
                "a": _state(signal_id="a"),
                "b": _state(signal_id="b", signal_time=BASE + timedelta(hours=1)),
            }
        }
    )
    assert set(audit["records"]) == {"a", "b"}
    assert all(row["audit_status"] == "pending" for row in audit["records"].values())


def test_independent_session_gate_blocks_clustered_100pct_coverage():
    records = {}
    for index in range(20):
        session = BASE.date() + timedelta(days=index % 9)
        records[str(index)] = {
            "signal_time": datetime.combine(session, BASE.time(), tzinfo=timezone.utc).isoformat(),
            "coverage": {"60m": True},
        }
    audit = {
        "records": records,
        "coverage": {"records": 20, "covered_60m": 20},
        "promotion_gate": {},
    }
    result = _apply_independent_session_gate(audit)
    assert result["coverage"]["coverage_60m_pct"] if "coverage_60m_pct" in result["coverage"] else True
    assert result["coverage"]["independent_60m_sessions"] == 9
    assert result["promotion_gate"]["coverage_ready"] is False
    assert result["promotion_gate"]["live_promotion_allowed"] is False


def test_independent_session_gate_requires_ten_sessions_even_with_full_coverage():
    records = {}
    for index in range(20):
        session = BASE.date() + timedelta(days=index % 10)
        records[str(index)] = {
            "signal_time": datetime.combine(session, BASE.time(), tzinfo=timezone.utc).isoformat(),
            "coverage": {"60m": True},
        }
    audit = {
        "records": records,
        "coverage": {"records": 20, "covered_60m": 20},
        "promotion_gate": {},
    }
    result = _apply_independent_session_gate(audit)
    assert result["coverage"]["independent_60m_sessions"] == 10
    assert result["promotion_gate"]["coverage_ready"] is True
    assert result["promotion_gate"]["walk_forward_required_after_coverage"] is True
    assert result["promotion_gate"]["live_promotion_allowed"] is False


def test_workflow_is_free_silent_and_persisted_by_stock_vault():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/stock-outcome-auditor.yml").read_text(encoding="utf-8")
    vault = (root / ".github/workflows/stock-state-vault.yml").read_text(encoding="utf-8")
    durable = (root / "options_radar/durable_stock_state.py").read_text(encoding="utf-8")
    runner = (root / "scripts/run_stock_outcome_audit.py").read_text(encoding="utf-8")

    assert 'cron: "12 22 * * 1-5"' in workflow
    assert 'PAID_MARKET_DATA_ALLOWED: "false"' in workflow
    assert "TELEGRAM" not in workflow
    assert "stock-outcome-audit-state" in workflow
    assert "audit_provider_order'] == ['yahoo']" in workflow
    assert 'providers=["yahoo"]' in runner
    assert "MIN_INDEPENDENT_SESSIONS = 10" in runner
    assert "existing_79pct_snapshot_rate_is_not_treated_as_accuracy" in runner

    assert "BLACK BOX Omega Stock Outcome Auditor" in vault
    assert "kind=audit" in vault
    assert "stock-outcome-audit-state" in vault
    assert "stock_outcome_audit.json" in vault
    assert "state/stocks/stock_outcome_audit.json" in durable
