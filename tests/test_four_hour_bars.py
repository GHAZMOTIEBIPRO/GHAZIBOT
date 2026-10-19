"""4H candles: session-aligned, built only from complete 15m blocks (no repaint)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from scripts.build_index_chart_snapshot import chart_report
from scripts.build_index_context import NY, bar_minutes, four_hour_from_quarters


def _quarters(day: str, end: str = "16:00") -> pd.DatetimeIndex:
    return pd.date_range(f"{day} 09:30", f"{day} {end}", freq="15min", tz=NY, inclusive="left")


def _frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    base = np.arange(len(index), dtype=float)
    return pd.DataFrame({"Open": base + 100, "High": base + 101, "Low": base + 99,
                         "Close": base + 100.5, "Volume": 1000.0}, index=index)


def test_full_session_gives_two_blocks_with_exact_ohlcv():
    out = four_hour_from_quarters(_frame(_quarters("2026-10-19")))
    assert [t.strftime("%H:%M") for t in out.index] == ["09:30", "13:30"]
    first = out.iloc[0]
    assert (first.Open, first.High, first.Low, first.Close, first.Volume) == (100, 116, 99, 115.5, 16000)
    assert [bar_minutes(t, "4h") for t in out.index] == [240, 150]


def test_open_or_gapped_block_is_never_published():
    index = _quarters("2026-10-19").append(_quarters("2026-10-20", "14:00"))
    out = four_hour_from_quarters(_frame(index))
    assert len(out) == 3  # Tuesday 13:30 block still forming
    gapped = _frame(_quarters("2026-10-19")).drop(pd.Timestamp("2026-10-19 10:15", tz=NY))
    assert [t.strftime("%H:%M") for t in four_hour_from_quarters(gapped).index] == ["13:30"]


def test_early_close_session_publishes_no_partial_4h_bar():
    out = four_hour_from_quarters(_frame(_quarters("2026-11-27", "13:00")))
    assert out.empty


def test_index_chart_report_exposes_4h_as_derived_research_interval():
    index = _quarters("2026-10-16").append(_quarters("2026-10-19"))
    now = datetime(2026, 10, 19, 20, 30, tzinfo=timezone.utc)
    daily = pd.DataFrame({"Open": [1.0] * 60, "High": [2.0] * 60, "Low": [0.5] * 60,
                          "Close": [1.5] * 60, "Volume": [10.0] * 60},
                         index=pd.date_range("2026-07-20", periods=60, freq="B", tz=NY))
    report = chart_report({"SPY": daily}, {"SPY": _frame(index)}, {}, now=now)
    four = report["symbols"]["SPY"]["intervals"]["4h"]
    assert len(four["bars"]) == 4
    assert four["derived_from"] == "session_aligned_completed_15m_yahoo_bars"
    assert four["research_only"] is True


def test_stock_watch_report_stays_within_its_size_cap_without_4h():
    from scripts.build_stock_watch_charts import WATCH, pack_symbol
    index = _quarters("2026-10-16").append(_quarters("2026-10-19"))
    now = datetime(2026, 10, 19, 20, 30, tzinfo=timezone.utc)
    daily = pd.DataFrame({"Open": [1.0] * 60, "High": [2.0] * 60, "Low": [0.5] * 60,
                          "Close": [1.5] * 60, "Volume": [10.0] * 60},
                         index=pd.date_range("2026-07-20", periods=60, freq="B", tz=NY))
    item = pack_symbol(min(WATCH), daily, _frame(index), None, now=now)
    assert item is not None and "4h" not in item["intervals"]
