"""Validate free deployment budget guard and avoid stale static metadata."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.vercel_metadata_budget_guard import MIN_INTERVAL_MINUTES, should_mirror

OLD=datetime(2026,10,18,10,tzinfo=timezone.utc)


def event(offset:int)->dict:
    return {"generated_at":(OLD+timedelta(minutes=offset)).isoformat(),
            "status":"degraded"}


def test_mirror_stays_stable_for_frequent_bot_state_scans():
    assert MIN_INTERVAL_MINUTES==360
    assert should_mirror(event(0),event(0),event(5),event(5)) is False
    assert should_mirror(event(0),event(0),event(89),event(89)) is False
    assert should_mirror(event(0),event(0),event(90),event(90)) is False
    assert should_mirror(event(0),event(0),event(150),event(150)) is False
    assert should_mirror(event(0),event(0),event(360),event(360)) is True


def test_mirror_does_not_replace_newer_file_with_an_older_runtime_snapshot():
    assert should_mirror(event(120),event(120),event(90),event(90)) is False
    assert should_mirror(event(120),event(120),event(240),event(200)) is False


def test_missing_or_invalid_existing_metadata_repairs_one_static_fallback():
    assert should_mirror({},event(0),event(1),event(1)) is True
    assert should_mirror(event(0),{},event(1),event(1)) is True
    with pytest.raises(ValueError, match="timezone-aware"):
        should_mirror(event(0),event(0),
                      {"generated_at":"2026-10-18T10:10:00"},event(120))


def test_bad_input_never_promoted():
    with pytest.raises(ValueError, match="timezone-aware"):
        should_mirror(event(0),event(0),{"generated_at":"unknown"},event(120))
    with pytest.raises(ValueError,match="at least"):
        should_mirror(event(0),event(0),event(90),event(90),
                      min_interval_minutes=10)


def test_both_publishers_apply_same_budget_guard():
    live=Path(".github/workflows/live-dashboard-status.yml").read_text(encoding="utf-8")
    omega=Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    for source in (live,omega):
        assert "scripts/vercel_metadata_budget_guard.py" in source
        assert '--old-health ' in source and '--old-status ' in source
        assert '--new-health ' in source and '--new-status ' in source
        assert 'if [[ "$budget_action" == "SKIP" ]]' in source
        assert "Mirror " in source
