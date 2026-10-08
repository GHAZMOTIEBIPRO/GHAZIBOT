from datetime import datetime, timezone

from scripts.explosion_hunter_research import build_report


def test_hunter_report_fails_closed_on_missing_provenance():
    report = build_report(
        {"symbols": {"ABC": {
            "rvol": 5, "float_shares": 1000000,
            "dollar_volume": 1000000, "day_move_pct": 5,
        }}},
        now=datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc),
    )
    assert report["research_only"] is True
    assert report["telegram_enabled"] is False
    assert report["watch_count"] == 0
    assert report["candidates"][0]["stage"] == "RESEARCH_ONLY"


def test_hunter_report_uses_only_provider_timestamp():
    now = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    report = build_report(
        {"generated_at": now.isoformat(), "symbols": {"ABC": {
            "rvol": 5, "float_shares": 1000000,
            "dollar_volume": 1000000, "day_move_pct": 5,
            "official_catalyst_url": "https://www.sec.gov/example",
        }}},
        now=now,
    )
    assert report["watch_count"] == 0
