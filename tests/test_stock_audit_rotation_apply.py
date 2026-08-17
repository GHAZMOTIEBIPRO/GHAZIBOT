from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from options_radar.stock_audit_rotation import (
    apply_symbol_bars_fair,
    migrate_and_classify_records,
)

NOW = datetime(2026, 8, 17, 23, 0, tzinfo=timezone.utc)
SIGNAL = datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc)


def _base(signal_id: str, *, status: str) -> dict:
    return {
        "signal_id": signal_id,
        "signal_time": SIGNAL.isoformat(),
        "symbol": "SAME",
        "direction": "up",
        "entry_price": 100.0,
        "entry_stage": "EXPLOSION",
        "entry_score": 85.0,
        "follow_through_target_pct": 6.0,
        "failure_threshold_pct": 6.0,
        "audit_status": status,
        "decision_authority": False,
        "snapshot_terminal_outcome": "open",
        "coverage": {"60m": status == "success", "1d": False},
    }


def test_resolved_row_same_symbol_is_not_re_evaluated():
    resolved = {
        **_base("resolved", status="success"),
        "audit_reason": "existing_terminal",
        "audit_terminal_at": "2026-08-13T14:20:00+00:00",
        "audited_at": "2026-08-16T22:00:00+00:00",
        "audit_attempt_count": 1,
    }
    pending = _base("pending", status="pending")
    audit = {"records": {"resolved": resolved, "pending": pending}}
    migrate_and_classify_records(audit)

    bars = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 100.0],
            "High": [101.0, 107.0, 108.0],
            "Low": [99.0, 99.0, 99.0],
            "Close": [100.0, 106.0, 107.0],
            "Volume": [1000, 1000, 1000],
        },
        index=pd.DatetimeIndex(
            [
                SIGNAL,
                datetime(2026, 8, 13, 14, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc),
            ]
        ),
    )

    updated = apply_symbol_bars_fair(
        audit,
        symbol="SAME",
        bars=bars,
        now=NOW,
        source="yahoo | historical",
    )
    assert updated == 1
    assert audit["records"]["resolved"]["audit_reason"] == "existing_terminal"
    assert audit["records"]["resolved"]["audit_terminal_at"] == "2026-08-13T14:20:00+00:00"
    assert audit["records"]["resolved"]["audited_at"] == "2026-08-16T22:00:00+00:00"
    assert audit["records"]["pending"]["audit_status"] == "success"
    assert audit["records"]["pending"]["audit_reason"] == "target_touched_first_in_observed_5m_sequence"
