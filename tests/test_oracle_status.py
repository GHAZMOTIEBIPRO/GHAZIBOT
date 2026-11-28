"""Public ORACLE status: statuses and counts only, never Alpaca values."""
import json
from datetime import datetime, timezone

from scripts import build_oracle_status as bos


def test_status_reads_markers_and_leaks_no_values(tmp_path):
    state, data = tmp_path / "state", tmp_path / "data"
    day = state / "daily_plan" / "2026-11-30"
    day.mkdir(parents=True)
    (day / "report_EARLY.json").write_text(json.dumps({"status": "DELIVERED", "late": False, "late_minutes": 2,
                                                       "messages": 6, "accepted": 6, "fingerprints": {"NVDA": "abc"},
                                                       "items": {"x": {"status": "DELIVERED"}}}))
    (day / "session_POSTCLOSE.json").write_text(json.dumps({"status": "DELIVERED", "scorecard": {"maps": 14, "t1": 3}}))
    (state / "options_hunter").mkdir(parents=True)
    (state / "options_hunter" / "last_top.json").write_text(json.dumps({"day": "2026-11-30", "updated_at": "2026-11-30T20:00:00+00:00", "tags": ["h1", "h2"]}))
    out = bos.build(state, data, datetime(2026, 11, 30, 22, 0, tzinfo=timezone.utc))
    assert out["day"]["reports"]["EARLY"]["status"] == "DELIVERED" and "scorecard" not in out["day"]
    assert out["event_engines"] == "NO_STORED_STATE" and "options_hunter" not in out
    assert out["sec_registry"]["status"] == "NOT_CONFIGURED"
    text = json.dumps(out)
    assert "fingerprints" not in text and "NVDA" not in text and "h1" not in text  # nothing symbol-level
    assert all(f["public"] is (f["name"] == "SEC EDGAR") for f in out["feeds"])
