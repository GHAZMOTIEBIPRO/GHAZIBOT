from datetime import datetime, timezone

from options_radar.explosion_hunter_profile import PROFILE, classify_candidate


def test_aggressive_profile():
    assert PROFILE.target_return_pct == 100
    assert PROFILE.sessions == ("PREMARKET", "REGULAR")


def test_missing_evidence_fails_closed():
    result = classify_candidate({"symbol": "abc", "rvol": 8})
    assert result["stage"] == "RESEARCH_ONLY"
    assert "FLOAT_UNVERIFIED" in result["flags"]
    assert result["target_is_probability"] is False


def test_watch_requires_inputs():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00Z",
        "official_catalyst_url": "https://www.sec.gov/example",
    }
    assert classify_candidate(row, now=datetime(2026, 10, 7, 15, 5, tzinfo=timezone.utc))["stage"] == "WATCH"
    row["day_move_pct"] = 80
    assert "CHASE_RISK" in classify_candidate(row)["flags"]

def test_stale_quote_never_becomes_watch():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00Z",
        "official_catalyst_url": "https://www.sec.gov/example",
    }
    result = classify_candidate(row, now=datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))
    assert result["stage"] == "RESEARCH_ONLY"
    assert "QUOTE_TIMESTAMP_STALE_OR_INVALID" in result["flags"]


def test_naive_and_future_timestamp_fail_closed():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00",
        "official_catalyst_url": "https://www.sec.gov/example",
    }
    now = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    assert classify_candidate(row, now=now)["stage"] == "RESEARCH_ONLY"
    row["provider_quote_timestamp"] = "2026-10-07T15:10:00Z"
    assert classify_candidate(row, now=now)["stage"] == "RESEARCH_ONLY"
