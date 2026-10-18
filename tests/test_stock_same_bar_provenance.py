"""Prevent false multi-provider confirmation from stale candles or Yahoo aliases."""
from datetime import datetime

import pandas as pd

from options_radar.data_fabric import reconcile_stock_bars


def bars(times: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Open":closes, "High":[p+1 for p in closes],
       "Low":[p-1 for p in closes], "Close":closes, "Volume":[100]*len(closes)},
       index=pd.to_datetime(times, utc=True))


def test_single_vendor_never_confirms_itself() -> None:
    row=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,101])
    _,source,audit=reconcile_stock_bars({"yahoo":row})
    assert source=="yahoo"
    assert audit["consensus_pass"] is False
    assert audit["matched_bar_independent_source_count"]==1
    assert audit["reason"]=="NO_INDEPENDENT_MATCHED_CANDLE"


def test_two_yahoo_transport_aliases_are_not_independent() -> None:
    row=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,101])
    _,_,a=reconcile_stock_bars({"yahoo":row,"yahooquery":row.copy()})
    assert a["source_count"]==2
    assert a["independent_source_count"]==1
    assert a["matched_bar_independent_source_count"]==1
    assert a["consensus_pass"] is False


def test_stale_old_bar_cannot_confirm_or_override_recent_bar() -> None:
    fresh=bars(["2026-10-16T14:05:00Z","2026-10-16T14:10:00Z"],[100,101])
    stale=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,101])
    selected,source,a=reconcile_stock_bars({"yahoo":fresh,"tradier":stale})
    assert source=="yahoo"
    assert selected.index[-1]==fresh.index[-1]
    assert a["independent_source_count"]==2
    assert a["matched_bar_independent_source_count"]==1
    assert a["unmatched_bar_provider_count"]==1
    assert a["consensus_pass"] is False


def test_two_independent_matching_intraday_bars_confirm() -> None:
    a=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,101])
    b=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,101.03])
    selected,source,proof=reconcile_stock_bars({"yahoo":a,"alpaca":b})
    assert source=="alpaca"
    assert proof["consensus_pass"] is True
    assert proof["matched_bar_independent_source_count"]==2
    assert proof["reason"]=="MATCHED_INDEPENDENT_BAR_AGREEMENT"
    assert selected["Close"].iloc[-1]==101.03


def test_price_divergence_is_a_negative_consensus() -> None:
    a=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,100])
    b=bars(["2026-10-16T14:00:00Z","2026-10-16T14:05:00Z"],[100,120])
    _,_,proof=reconcile_stock_bars({"alpaca":a,"yahoo":b})
    assert proof["consensus_pass"] is False
    assert proof["reason"]=="PRICE_DISAGREEMENT"


def test_one_day_bars_match_by_new_york_session_not_utc_midnight() -> None:
    # Yahoo source 00:00 America/New_York = 04:00 UTC on Oct 16.
    yahoo=bars(["2026-10-15T04:00:00Z","2026-10-16T04:00:00Z"],[100,101])
    alpaca=bars(["2026-10-15T05:00:00Z","2026-10-16T05:00:00Z"],[100,101.01])
    _,_,proof=reconcile_stock_bars({"yahoo":yahoo,"alpaca":alpaca})
    assert proof["bar_granularity"]=="1d"
    assert proof["matched_bar_independent_source_count"]==2
    assert proof["consensus_pass"] is True


def test_different_exchange_sessions_cannot_be_matching() -> None:
    old=bars(["2026-10-14T04:00:00Z","2026-10-15T04:00:00Z"],[100,101])
    new=bars(["2026-10-15T04:00:00Z","2026-10-16T04:00:00Z"],[100,101])
    _,_,proof=reconcile_stock_bars({"yahoo":new,"alpaca":old})
    assert proof["consensus_pass"] is False


def test_invalid_prices_and_non_dates_are_excluded() -> None:
    bad=bars(["2026-10-16T14:00:00Z"],[-10])
    assert reconcile_stock_bars({"alpaca":bad})[2]["source_count"]==0
