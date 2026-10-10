from datetime import datetime, timezone

from options_radar.explosion_hunter_profile import PROFILE, classify_candidate, is_verified_sec_url


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
        "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/123/abc.htm",
    }
    assert classify_candidate(row, now=datetime(2026, 10, 7, 15, 5, tzinfo=timezone.utc))["stage"] == "WATCH"
    row["day_move_pct"] = 80
    assert "CHASE_RISK" in classify_candidate(row)["flags"]

def test_stale_quote_never_becomes_watch():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00Z",
        "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/123/abc.htm",
    }
    result = classify_candidate(row, now=datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))
    assert result["stage"] == "RESEARCH_ONLY"
    assert "QUOTE_TIMESTAMP_STALE_OR_INVALID" in result["flags"]


def test_naive_and_future_timestamp_fail_closed():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00",
        "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/123/abc.htm",
    }
    now = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    assert classify_candidate(row, now=now)["stage"] == "RESEARCH_ONLY"
    row["provider_quote_timestamp"] = "2026-10-07T15:10:00Z"
    assert classify_candidate(row, now=now)["stage"] == "RESEARCH_ONLY"

def test_sec_link_rejects_spoofed_hosts_and_non_filing_pages():
    assert is_verified_sec_url("https://www.sec.gov/Archives/edgar/data/123/abc.htm")
    assert not is_verified_sec_url("https://sec.gov.evil.example/Archives/abc")
    assert not is_verified_sec_url("https://evil.example@www.sec.gov.evil.example/Archives/abc")
    assert not is_verified_sec_url("http://www.sec.gov/Archives/abc")
    assert not is_verified_sec_url("https://www.sec.gov.evil.example/Archives/abc")
    assert not is_verified_sec_url("https://www.sec.gov/news/press-release")
    assert not is_verified_sec_url("https://www.sec.gov:444/Archives/abc")


def test_unverified_catalyst_blocks_watch_even_with_fresh_quote():
    row = {
        "symbol": "ABC", "rvol": 3, "float_shares": 1_000_000,
        "dollar_volume": 2_000_000, "day_move_pct": 5,
        "provider_quote_timestamp": "2026-10-07T15:00:00Z",
        "official_catalyst_url": "https://sec.gov.evil.example/Archives/fake",
    }
    result = classify_candidate(row, now=datetime(2026, 10, 7, 15, 5, tzinfo=timezone.utc))
    assert result["stage"] == "RESEARCH_ONLY"
    assert "SEC_CATALYST_PROVENANCE_UNVERIFIED" in result["flags"]

def test_high_dilution_blocks_strict_watch_even_when_quote_and_sec_are_fresh():
    row = {
        "symbol": "ABC",
        "price": 4.0,
        "market_cap": 40_000_000,
        "rvol": 4,
        "float_shares": 1_500_000,
        "dollar_volume": 3_000_000,
        "day_move_pct": 6,
        "supply_score": 90,
        "dilution_risk": 90,
        "catalyst_headline": "Active ATM offering under S-3 and 424B5",
        "provider_quote_timestamp": "2026-10-07T15:00:00Z",
        "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/123/abc.htm",
    }
    result = classify_candidate(
        row,
        now=datetime(2026, 10, 7, 15, 5, tzinfo=timezone.utc),
    )
    assert result["stage"] == "RESEARCH_ONLY"
    assert "MICROCAP_DILUTION_OR_STRUCTURE_RISK" in result["flags"]
    assert result["microcap_hunter"]["stage"] == "AVOID_RISK"

