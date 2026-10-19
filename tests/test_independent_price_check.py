"""Licensed independent close cross-check: keyed + attested vendors only, no prices published."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.independent_price_check import (
    CHECK_SYMBOLS,
    TOLERANCE_BPS,
    eligible_families,
    run_check,
)
from scripts.build_site_strength import score
from scripts.build_source_consensus_status import summarize

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)  # Wednesday


def _bars(closes):
    days = pd.DatetimeIndex(["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"], tz="America/New_York")
    return pd.DataFrame({"Close": closes}, index=days[: len(closes)])


def test_only_keyed_and_owner_attested_families_are_eligible():
    env = {"TIINGO_API_KEY": "k", "TIINGO_NON_DISPLAY_USE_AUTHORIZED": "true",
           "ALPACA_API_KEY": "a", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
           "TWELVE_DATA_API_KEY": "t", "POLYGON_NON_DISPLAY_USE_AUTHORIZED": "true"}
    # Alpaca lacks its secret; Twelve Data lacks attestation; Polygon lacks a key.
    assert eligible_families(env) == ["tiingo"]
    env["ALPACA_SECRET_KEY"] = "s"
    assert eligible_families(env) == ["tiingo", "alpaca"]


def test_agreeing_vendors_verify_and_today_partial_session_is_ignored():
    def fetch(family, symbol):
        # Wednesday's (today) bar disagrees but is not a completed session.
        return _bars([100.0, 101.0, 102.0, 150.0 if family == "alpaca" else 103.0])
    report = run_check(fetch, ["tiingo", "alpaca"], now=NOW)
    assert report["status"] == "VERIFIED_LICENSED"
    assert report["sessions_compared"] == ["2026-10-20"]
    assert report["symbols_compared"] == len(CHECK_SYMBOLS)
    assert report["confirming_families"] == ["alpaca", "tiingo"]
    assert report["price_data_published"] is False
    assert "102.0" not in str(report)


def test_disagreement_errors_or_a_single_family_never_verify():
    off = 1 + 2 * TOLERANCE_BPS / 10_000
    bad = run_check(lambda f, s: _bars([100.0, 101.0, 102.0 * (off if f == "alpaca" else 1)]),
                    ["tiingo", "alpaca"], now=NOW)
    assert bad["status"] == "NOT_VERIFIED" and bad["symbols_agreeing"] == 0

    def boom(family, symbol):
        raise RuntimeError("https://api.example/?token=SECRET")
    failed = run_check(boom, ["tiingo", "alpaca"], now=NOW)
    assert failed["status"] == "NOT_VERIFIED" and "SECRET" not in str(failed)
    single = run_check(lambda f, s: _bars([1.0, 2.0, 3.0]), ["tiingo"], now=NOW)
    assert single["status"] == "INSUFFICIENT_LICENSED_SOURCES"


def _charts():
    return {"schema": "ghazi.stock_charts.v1", "generated_at": NOW.isoformat(),
            "quote_execution_eligible": False, "provider_source_family": "yahoo",
            "coverage": {"requested": 20, "with_valid_charts": 20, "with_daily": 20,
                         "with_1h": 20, "with_15m": 20, "with_5m": 20}}


def test_twenty_points_require_a_fresh_verified_licensed_check_end_to_end():
    verified = run_check(lambda f, s: _bars([100.0, 101.0, 102.0]), ["tiingo", "alpaca"], now=NOW)
    for check, expected in ((None, 0), ({**verified, "status": "NOT_VERIFIED"}, 0),
                            ({**verified, "generated_at": (NOW - timedelta(hours=40)).isoformat()}, 0),
                            ({**verified, "price_data_published": True}, 0),
                            (verified, 20)):
        agreement = summarize(_charts(), now=NOW, check=check)
        result = score(charts=_charts(), agreement=agreement, sec={}, free_options={},
                       walk_forward={}, now=NOW)
        earned = {c["id"]: c["earned"] for c in result["components"]}["independent_prices"]
        assert earned == expected, (check and check.get("status"), earned)
    assert summarize(_charts(), now=NOW, check=verified)["price_data"] is None


def test_two_vendor_gap_is_measured_as_the_full_spread():
    from datetime import date

    from options_radar.independent_price_check import compare_symbol
    just_inside = compare_symbol({"a": {date(2026, 10, 20): 100.0}, "b": {date(2026, 10, 20): 100.24}},
                                 before=date(2026, 10, 21))
    just_outside = compare_symbol({"a": {date(2026, 10, 20): 100.0}, "b": {date(2026, 10, 20): 100.30}},
                                  before=date(2026, 10, 21))
    assert just_inside["agree"] is True and just_outside["agree"] is False
    assert just_outside["max_divergence_bps"] > TOLERANCE_BPS
