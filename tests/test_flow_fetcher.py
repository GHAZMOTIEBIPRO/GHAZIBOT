from __future__ import annotations

import pandas as pd

from options_radar.flow_fetcher import _normalise_provider_timestamp
from options_radar.hybrid_fetcher import DataFetcher


def test_tradier_millisecond_epoch_is_not_read_as_1970():
    value = _normalise_provider_timestamp(1757948483351)
    assert isinstance(value, pd.Timestamp)
    assert value.year == 2025
    assert value.tzinfo is not None


def test_data_fetcher_row_uses_installed_timestamp_normalizer():
    row = DataFetcher._build_option_row(
        symbol="NVDA",
        contract="NVDA250919C00175000",
        expiry="2025-09-19",
        strike=175,
        side="call",
        bid=2.86,
        ask=2.88,
        last=2.87,
        volume=38156,
        open_interest=76023,
        iv=0.358,
        delta=0.56,
        gamma=0.05,
        theta=-0.33,
        vega=0.07,
        underlying=175.23,
        updated_at=1757948483351,
        source="tradier",
        data_quality=0.9,
        freshness="brokerage feed",
    )
    assert row["updated_at"].year == 2025


def test_option_row_keeps_last_trade_semantics_separate_from_quote_time():
    row = DataFetcher._build_option_row(
        symbol="NVDA",
        contract="NVDA250919C00175000",
        expiry="2025-09-19",
        strike=175,
        side="call",
        bid=2.86,
        ask=2.88,
        last=2.87,
        volume=38156,
        open_interest=76023,
        iv=0.358,
        delta=0.56,
        gamma=0.05,
        theta=-0.33,
        vega=0.07,
        underlying=175.23,
        updated_at=1757948483351,
        quote_timestamp=None,
        last_trade_timestamp=1757948483351,
        timestamp_kind="last_trade",
        source="tradier",
        data_quality=0.9,
        freshness="brokerage feed",
    )
    assert row["timestamp_kind"] == "last_trade"
    assert pd.isna(row["quote_timestamp"])
    assert row["last_trade_timestamp"].year == 2025
    assert row["updated_at"].year == 2025


def test_hybrid_schema_carries_timestamp_provenance_fields():
    from options_radar.hybrid_fetcher import OPTION_COLUMNS

    assert "quote_timestamp" in OPTION_COLUMNS
    assert "last_trade_timestamp" in OPTION_COLUMNS
    assert "timestamp_kind" in OPTION_COLUMNS
