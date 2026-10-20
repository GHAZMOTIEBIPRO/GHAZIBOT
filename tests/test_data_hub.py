import json
from datetime import datetime, timezone

from scripts.build_data_hub import REGISTRY, assess, build

TUE_OPEN = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
TUE_NIGHT = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
ENTRY = next(e for e in REGISTRY if e["file"] == "liquidity_map.json")  # cadence 60


def test_freshness_uses_dataset_timestamp_and_cadence():
    fresh = assess(ENTRY, {"generated_at": "2026-10-20T13:00:00+00:00"}, TUE_OPEN)
    assert fresh["freshness"] == "FRESH" and fresh["age_minutes"] == 120.0
    stale = assess(ENTRY, {"generated_at": "2026-10-20T10:00:00+00:00"}, TUE_OPEN)
    assert stale["freshness"] == "STALE"  # 300 min > 3 x 60 during the session
    overnight = assess(ENTRY, {"generated_at": "2026-10-19T20:00:00+00:00"}, TUE_NIGHT)
    assert overnight["freshness"] == "FRESH"  # 7h overnight is within the 18h tolerance


def test_missing_untimed_future_and_guard_failures():
    assert assess(ENTRY, None, TUE_OPEN)["freshness"] == "MISSING"
    assert assess(ENTRY, {"x": 1}, TUE_OPEN)["freshness"] == "UNTIMED"
    assert assess(ENTRY, {"generated_at": "2026-10-20T16:00:00+00:00"}, TUE_OPEN)["freshness"] == "FUTURE_TIMESTAMP"
    bad = assess(ENTRY, {"generated_at": "2026-10-20T14:00:00+00:00", "execution_grade": True}, TUE_OPEN)
    assert bad["validation"] == "FAIL" and bad["validation_problems"] == ["execution_grade!=False"]


def test_build_catalogs_every_registered_file(tmp_path):
    (tmp_path / "liquidity_map.json").write_text(json.dumps({"generated_at": "2026-10-20T14:30:00+00:00"}))
    (tmp_path / "index_radar.json").write_text("{not json")
    report = build(tmp_path, TUE_OPEN)
    rows = {r["file"]: r for r in report["datasets"]}
    assert len(rows) == len(REGISTRY)
    assert rows["liquidity_map.json"]["freshness"] == "FRESH"
    assert rows["index_radar.json"]["validation"] == "FAIL"
    assert rows["options_analytics.json"]["freshness"] == "MISSING"
    assert report["summary"]["fallback_sources"] == []
    assert rows["stock_watch_charts.json"]["license_class"] == "TERMS_RESTRICTED"
    assert set(report["source_gates"]) == {"cboe_delayed", "yahoo", "nasdaq_web"}
    assert report["policy"]["network_requests"] is False
