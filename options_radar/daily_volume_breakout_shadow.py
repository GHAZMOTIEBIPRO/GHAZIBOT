"""Unusual-volume and 55-session breakout/retest *shadow*, not a trade signal.

Independent, deterministic research inspired by common volume anomaly and
price-action screeners. No upstream source code, market fetch, Yahoo bypass,
broker automation, implied execution readiness or calibrated probability.
Only original, ordered, completed daily OHLCV bars can enter this function.
"""
from __future__ import annotations

import math
from statistics import median

import pandas as pd

from options_radar.vcp_minervini_shadow import _valid

SCHEMA = "ghazi.daily_volume_breakout_shadow.v1"
MIN_BARS = 70
LOOKBACK_HIGH = 55
VOLUME_WINDOW = 20
SURGE_RATIO = 2.0
BREAKOUT_VOLUME_RATIO = 1.5
STAGES = frozenset({
    "INSUFFICIENT", "BREAKOUT_VOLUME_WATCH", "BREAKOUT_PRICE_ONLY",
    "RETEST_HOLD_WATCH", "HIGH_VOLUME_DOWN_RISK", "VOLUME_SPIKE_WATCH", "NO_PATTERN",
})


def daily_volume_breakout_shadow(frame: pd.DataFrame) -> dict:
    base = {
        "schema": SCHEMA, "available": False, "stage": "INSUFFICIENT",
        "source_family": "yahoo", "source_last_daily_bar": None,
        "source_timeframe": "completed_1d",
        "research_only": True, "independent_confirmation": False,
        "source_independence": False, "options_execution_eligible": False,
        "data_role": "PRICE_VOLUME_RESEARCH_ONLY",
        "previous_55d_high": None, "previous_day_close": None,
        "last_close": None, "volume_ratio_to_prior_20_median": None,
        "volume_spike": None, "breakout_above_prior_55d_high": None,
        "retest_hold": None, "closed_bars": 0,
        "note_ar": "قراءة بحثية من حجم بورصة/مصدر واحد، لا تثبت مشتريًا مؤسسيًا أو تدفق عقود.",
    }
    if not _valid(frame) or len(frame) < MIN_BARS:
        return base
    rows = [
        (float(o), float(h), float(l), float(c), float(v))
        for o, h, l, c, v in
        frame[["Open", "High", "Low", "Close", "Volume"]].tail(85)
        .itertuples(index=False, name=None)
    ]
    volumes_before = [v for _, _, _, _, v in rows[-(VOLUME_WINDOW + 1):-1]]
    base_volume = float(median(volumes_before))
    if not math.isfinite(base_volume) or base_volume <= 0:
        return base
    _, _, low, close, volume = rows[-1]
    prev_close = rows[-2][3]
    ratio = volume / base_volume
    prior_high = max(x[1] for x in rows[-(LOOKBACK_HIGH + 1):-1])
    # Yesterday's breakout must be measured against an earlier window
    # excluding yesterday: no contaminated pivot, no future day.
    yesterday_high = max(x[1] for x in rows[-(LOOKBACK_HIGH + 2):-2])
    yesterday_broke_out = prev_close > yesterday_high
    retest_hold = yesterday_broke_out and low <= yesterday_high and close >= yesterday_high
    new_breakout = close > prior_high
    spike = ratio >= SURGE_RATIO
    high_volume_down = spike and close < prev_close
    if high_volume_down:
        stage = "HIGH_VOLUME_DOWN_RISK"
    elif new_breakout and ratio >= BREAKOUT_VOLUME_RATIO:
        stage = "BREAKOUT_VOLUME_WATCH"
    elif retest_hold:
        stage = "RETEST_HOLD_WATCH"
    elif new_breakout:
        stage = "BREAKOUT_PRICE_ONLY"
    elif spike:
        stage = "VOLUME_SPIKE_WATCH"
    else:
        stage = "NO_PATTERN"
    return {
        **base,
        "available": True, "stage": stage,
        "source_last_daily_bar": frame.index[-1].date().isoformat(),
        "closed_bars": len(rows),
        "previous_55d_high": round(prior_high, 4),
        "previous_day_close": round(prev_close, 4),
        "last_close": round(close, 4),
        "volume_ratio_to_prior_20_median": round(ratio, 3),
        "volume_spike": bool(spike),
        "breakout_above_prior_55d_high": bool(new_breakout),
        "retest_hold": bool(retest_hold),
    }
