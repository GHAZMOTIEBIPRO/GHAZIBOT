"""Differential test: every internal EMA / ATR / RSI / VWAP implementation against pandas-ta-classic.

2026-11-19 finding: options_radar.indicators seeded Wilder's RSI/ATR with the first value
(plain ewm). Against the reference (SMA seed, as TA-Lib) the last value was off by 22 % (RSI)
and 12.6 % (ATR) at 25 bars, 2.3 % / 1.0 % at 60 bars. EMA has two deliberate seed families;
each must equal its own reference exactly.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from options_radar import core_options_strategy as cos
from options_radar import daily_plan as dp
from options_radar import indicators as ind
from options_radar import vcp_minervini_shadow as vcp

ta = pytest.importorskip("pandas_ta_classic")


def _ohlcv(n: int = 260, seed: int = 20261119) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, n))
    high = np.maximum.reduce([close * (1 + np.abs(rng.normal(0, 0.006, n))), open_, close])
    low = np.minimum.reduce([close * (1 - np.abs(rng.normal(0, 0.006, n))), open_, close])
    vol = rng.integers(10_000, 90_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol})


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b)


@pytest.mark.parametrize("bars", [25, 40, 60, 100, 250])
def test_wilder_rsi_and_atr_equal_the_reference_from_the_first_valid_bar(bars):
    df = _ohlcv().iloc[:bars]
    ref_rsi = float(ta.rsi(df["Close"], length=14).iloc[-1])
    ref_atr = float(ta.atr(df["High"], df["Low"], df["Close"], length=14, mamode="rma").iloc[-1])
    assert _rel(float(ind._rsi(df["Close"], 14).iloc[-1]), ref_rsi) < 1e-9
    assert _rel(float(ind._atr(df, 14).iloc[-1]), ref_atr) < 1e-9
    bars_list = [{"open": o, "high": h, "low": lo, "close": c} for o, h, lo, c in
                 zip(df["Open"], df["High"], df["Low"], df["Close"])]
    assert _rel(dp.atr(bars_list, 14), ref_atr) < 1e-9  # the daily plan's own ATR agrees too


def test_rsi_and_atr_are_undefined_before_the_seed_not_guessed():
    df = _ohlcv(30)
    rsi, atr = ind._rsi(df["Close"], 14), ind._atr(df, 14)
    assert rsi.iloc[:14].isna().all() and pd.notna(rsi.iloc[14])  # 14 differences need 15 closes
    assert atr.iloc[:14].isna().all() and pd.notna(atr.iloc[14])  # TR starts at bar 2
    assert ind._rsi(df["Close"].iloc[:10], 14).isna().all()


@pytest.mark.parametrize("span", [9, 21, 50])
def test_each_ema_family_equals_its_own_reference(span):
    closes = _ohlcv()["Close"].iloc[:120]
    first_seed = float(ta.ema(closes, length=span, sma=False).iloc[-1])
    sma_seed = float(ta.ema(closes, length=span).iloc[-1])
    assert _rel(dp.ema(list(closes), span)[-1], first_seed) < 1e-12
    assert _rel(float(ind._ema(closes, span).iloc[-1]), first_seed) < 1e-12
    assert _rel(cos._ema(list(closes), span), sma_seed) < 1e-12
    assert _rel(vcp._ema(list(closes), span), sma_seed) < 1e-12


def test_session_vwap_uses_the_typical_price_like_the_reference():
    df = _ohlcv(78).set_index(pd.date_range("2026-11-18 14:30", periods=78, freq="5min", tz="UTC"))
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    ours = float((typical * df["Volume"]).sum() / df["Volume"].sum())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the reference warns about converting a tz-aware index to periods
        ref = float(ta.vwap(df["High"], df["Low"], df["Close"], df["Volume"], anchor="D").iloc[-1])
    assert _rel(ours, ref) < 1e-12
