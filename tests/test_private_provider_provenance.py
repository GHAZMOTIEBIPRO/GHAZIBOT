"""Prove private market data source labels distinguish Twelve Basic from IEX."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from options_radar.core_options_strategy import technical_levels

NY = ZoneInfo("America/New_York")


def _fixture():
    now = datetime(2026, 10, 30, 20, 5, tzinfo=timezone.utc)
    daily = []
    for day in (28, 29):
        start = datetime(2026, 10, day, 9, 30, tzinfo=NY)
        daily.append({"timestamp": start.astimezone(timezone.utc).isoformat(),
                      "open": 100, "high": 103, "low": 99,
                      "close": 101, "volume": 300_000})
    rows = []
    begin = datetime(2026, 10, 30, 9, 30, tzinfo=NY)
    for i in range(78):
        price = 100 + i / 100
        rows.append({"timestamp": (begin + timedelta(minutes=5 * i)).astimezone(timezone.utc).isoformat(),
                     "open": price, "high": price + .1, "low": price - .1,
                     "close": price + .02, "volume": 1200})
    return daily, rows, now


def test_same_validated_ohlcv_but_distinct_source_and_vwap_provenance():
    daily, rows, now = _fixture()
    alpaca = technical_levels("SPY", daily, rows, now=now)
    twelve = technical_levels("SPY", daily, rows, now=now,
                              provider="twelve_data_basic")
    assert alpaca["status"] == "RESEARCH_ONLY_IEX"
    assert alpaca["source"] == "ALPACA_IEX_5M_AND_DAILY"
    assert alpaca["source_scope"] == "IEX_PARTIAL_EXCHANGE_NOT_SIP"
    assert "vwap_5m_iex" in alpaca["levels"]
    assert "vwap_5m_twelve_data" not in alpaca["levels"]
    assert twelve["status"] == "RESEARCH_ONLY_TWELVE_DATA"
    assert twelve["source"] == "TWELVE_DATA_BASIC_PRIVATE_5M_AND_DAILY"
    assert twelve["source_scope"] == "TWELVE_DATA_BASIC_INTERNAL_NON_DISPLAY"
    assert "vwap_5m_twelve_data" in twelve["levels"]
    assert "vwap_5m_iex" not in twelve["levels"]
    assert twelve["execution_authority"] is False


def test_unknown_provider_cannot_inherit_iex_data_provenance():
    daily, rows, now = _fixture()
    result = technical_levels("SPY", daily, rows, now=now,
                              provider="imaginary_sip")
    assert result["status"] == "UNKNOWN_PROVIDER"
    assert result["decision"] == "WAIT"
    assert result["levels"] == {}
    assert result["execution_authority"] is False
