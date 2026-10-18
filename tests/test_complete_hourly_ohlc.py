"""Research-only hourly OHLC: exactly four CLOSED 15-minute Yahoo bars, no request."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.build_index_chart_snapshot import chart_report
from scripts.build_index_context import hourly_from_quarters
from scripts.build_stock_watch_charts import pack_symbol

NY = ZoneInfo("America/New_York")


def quarters(day="2026-10-16", count=28):
    idx = pd.date_range(day+" 09:30", periods=count, freq="15min", tz=NY)
    op = [100 + 0.2*i for i in range(len(idx))]
    return pd.DataFrame({
        "Open": op,
        "High": [x + 0.4 for x in op],
        "Low": [x - 0.3 for x in op],
        "Close": [x + 0.1 for x in op],
        "Volume": [1000]*len(idx),
    }, index=idx)


def test_aggregation_is_real_filled_ohlc_not_average_prices():
    source = quarters(count=8)
    hours = hourly_from_quarters(source)
    assert len(hours) == 2
    assert hours.index[0] == pd.Timestamp("2026-10-16 09:30", tz=NY)
    first = hours.iloc[0]
    assert first["Open"] == source.iloc[0]["Open"]
    assert first["High"] == source.iloc[:4]["High"].max()
    assert first["Low"] == source.iloc[:4]["Low"].min()
    assert first["Close"] == source.iloc[3]["Close"]
    assert first["Volume"] == sum(source.iloc[:4]["Volume"])


def test_missing_any_quarter_fails_closed_for_that_hour():
    source = quarters(count=8)
    missing = source.drop(pd.Timestamp("2026-10-16 10:00", tz=NY))
    hours = hourly_from_quarters(missing)
    assert len(hours) == 1
    assert hours.index[0] == pd.Timestamp("2026-10-16 10:30", tz=NY)


def test_hour_cannot_appear_before_final_quarter_closes():
    minute = quarters(count=8)
    early = datetime(2026, 10, 16, 10, 29, tzinfo=NY)
    late = datetime(2026, 10, 16, 10, 31, tzinfo=NY)
    old = pack_symbol("AAPL", None, minute, None, now=early)
    assert old is not None
    assert "1h" not in old["intervals"]
    done = pack_symbol("AAPL", None, minute, None, now=late)
    assert done["intervals"]["1h"]["bars"][-1]["time"] == int(
        pd.Timestamp("2026-10-16 09:30", tz=NY).timestamp()
    )
    assert done["intervals"]["1h"]["current_session_confirmed"] is True
    assert done["intervals"]["1h"]["derived_from"] == "four_completed_15m_yahoo_bars"
    assert done["options_execution_grade"] is False


def test_weekend_hourly_data_is_not_current_market_quote():
    weekend = datetime(2026, 10, 18, 12, tzinfo=NY)
    report = chart_report({}, {"SPX":quarters()}, {}, now=weekend)
    hour = report["symbols"]["SPX"]["intervals"]["1h"]
    assert hour["current_session_confirmed"] is False
    assert hour["research_only"] is True
    assert hour["derived_from"] == "four_completed_15m_yahoo_bars"
    stock = pack_symbol("AAPL", None, quarters(), None, now=weekend)
    assert stock["intervals"]["1h"]["current_session_confirmed"] is False
    assert stock["intervals"]["1h"]["bars"] == hour["bars"]


def test_hourly_uses_existing_index_and_stock_fetch_not_new_provider():
    html = Path("public/index.html").read_text(encoding="utf-8")
    idx = Path("scripts/build_index_chart_snapshot.py").read_text(encoding="utf-8")
    stocks = Path("scripts/build_stock_watch_charts.py").read_text(encoding="utf-8")
    assert '<option value="1h">ساعة</option>' in html
    assert '"1h": hourly_from_quarters(clean_15)' in stocks
    assert 'frames["1h"] = hourly_from_quarters(frames["15m"])' in idx
    assert '("1h", "5d")' not in stocks
    assert '("1h", "5d")' not in idx
    assert "four_completed_15m_yahoo_bars" in idx
    assert "four_completed_15m_yahoo_bars" in stocks
