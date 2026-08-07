from __future__ import annotations

from datetime import date

from options_radar.expiry_identity import classify_expiry, holding_horizon_bucket


def _row(
    expiration: str,
    *,
    symbol: str = "SPY",
    contract_symbol: str | None = None,
    option_root: str | None = None,
    **extra,
) -> dict:
    contract_symbol = contract_symbol or f"{symbol}260821C00500000"
    return {
        "symbol": symbol,
        "contract_symbol": contract_symbol,
        "expiration": expiration,
        "option_root": option_root,
        "source": "test-provider",
        **extra,
    }


def test_standard_monthly_stays_monthly_with_five_dte() -> None:
    identity = classify_expiry(
        _row("2026-08-21", contract_symbol="SPY260821C00500000"),
        as_of=date(2026, 8, 16),
    )
    assert identity.calendar_dte == 5
    assert identity.expiry_family == "STANDARD_MONTHLY"
    assert identity.dte_bucket == "3-7_DTE"
    assert identity.is_standard_monthly is True
    assert identity.is_weekly is False


def test_weekly_friday_can_be_twenty_dte() -> None:
    identity = classify_expiry(
        _row("2026-08-28", contract_symbol="SPY260828C00500000"),
        as_of=date(2026, 8, 8),
    )
    assert identity.calendar_dte == 20
    assert identity.expiry_family == "WEEKLY"
    assert identity.dte_bucket == "15-30_DTE"


def test_spx_standard_third_friday_is_am_settled_monthly() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-21",
            symbol="SPX",
            contract_symbol="SPX260821C06000000",
            option_root="SPX",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "STANDARD_MONTHLY"
    assert identity.option_root == "SPX"
    assert identity.settlement_type == "CASH"
    assert identity.settlement_time == "AM"
    assert identity.exercise_style == "EUROPEAN"


def test_spx_am_weekly_after_2026_approval_is_weekly() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-13",
            symbol="SPX",
            contract_symbol="SPX260813C06000000",
            option_root="SPX",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "WEEKLY"
    assert identity.classification_method == "product_rule_spx_am_weekly_2026"
    assert identity.settlement_time == "AM"


def test_spx_am_end_of_month_after_2026_approval_is_eom() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-31",
            symbol="SPX",
            contract_symbol="SPX260831C06000000",
            option_root="SPX",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "END_OF_MONTH"
    assert identity.classification_method == "product_rule_spx_am_eom_2026"
    assert identity.settlement_time == "AM"


def test_spxw_third_friday_remains_spxw_weekly_pm_settled() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-21",
            symbol="SPX",
            contract_symbol="SPXW260821C06000000",
            option_root="SPXW",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "WEEKLY"
    assert identity.option_root == "SPXW"
    assert identity.settlement_type == "CASH"
    assert identity.settlement_time == "PM"
    assert identity.exercise_style == "EUROPEAN"


def test_spy_standard_monthly_is_physical_american() -> None:
    identity = classify_expiry(
        _row("2026-08-21", contract_symbol="SPY260821P00500000"),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "STANDARD_MONTHLY"
    assert identity.settlement_type == "PHYSICAL"
    assert identity.exercise_style == "AMERICAN"


def test_spy_weekly_is_weekly() -> None:
    identity = classify_expiry(
        _row("2026-08-28", contract_symbol="SPY260828P00500000"),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "WEEKLY"


def test_holiday_shifted_third_friday_fallback() -> None:
    identity = classify_expiry(
        _row("2026-06-18", contract_symbol="SPY260618C00500000"),
        as_of=date(2026, 6, 10),
    )
    assert identity.expiry_family == "STANDARD_MONTHLY"
    assert identity.classification_method == "calendar_holiday_shift_fallback"
    assert identity.classification_confidence < 0.70


def test_spxw_end_of_month_series() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-31",
            symbol="SPX",
            contract_symbol="SPXW260831C06000000",
            option_root="SPXW",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "END_OF_MONTH"
    assert identity.is_end_of_month is True


def test_unknown_nonfriday_metadata_fallback_is_not_forced_weekly() -> None:
    identity = classify_expiry(
        _row("2026-08-26", symbol="AAPL", contract_symbol="AAPL260826C00200000"),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "UNKNOWN"
    assert identity.classification_method == "calendar_fallback_unknown"


def test_provider_metadata_overrides_third_friday_calendar() -> None:
    identity = classify_expiry(
        _row(
            "2026-08-21",
            contract_symbol="SPY260821C00500000",
            provider_expiry_family="weekly",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "WEEKLY"
    assert identity.classification_method == "provider_metadata:provider_expiry_family"
    assert identity.classification_confidence == 0.99


def test_explicit_quarterly_metadata_is_preserved() -> None:
    identity = classify_expiry(
        _row(
            "2026-09-30",
            contract_symbol="SPY260930C00500000",
            provider_expiry_family="quarterly",
        ),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "QUARTERLY"
    assert identity.is_quarterly is True


def test_long_dated_fallback_is_leaps_without_renaming_dte_bucket() -> None:
    identity = classify_expiry(
        _row("2028-01-21", contract_symbol="SPY280121C00500000"),
        as_of=date(2026, 8, 10),
    )
    assert identity.expiry_family == "LEAPS"
    assert identity.dte_bucket == "60+_DTE"


def test_holding_horizon_is_independent_of_expiry_family() -> None:
    assert holding_horizon_bucket(0) == "0DTE"
    assert holding_horizon_bucket(2) == "1-2_DTE"
    assert holding_horizon_bucket(5) == "3-7_DTE"
    assert holding_horizon_bucket(10) == "8-14_DTE"
    assert holding_horizon_bucket(20) == "15-30_DTE"
    assert holding_horizon_bucket(45) == "31-60_DTE"
    assert holding_horizon_bucket(90) == "60+_DTE"
