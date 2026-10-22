"""New 50-project integration: closed-bar unusual volume and retest research."""
from datetime import datetime

import pandas as pd

from options_radar.daily_volume_breakout_shadow import (
    SCHEMA,
    STAGES,
    daily_volume_breakout_shadow,
)
from scripts.build_stock_watch_charts import pack_symbol


def daily_bars(n=96):
    days = pd.bdate_range(end="2026-10-16", periods=n, tz="America/New_York")
    closes = [10 + 0.012 * i for i in range(n)]
    opens = [x - .02 for x in closes]
    highs = [x + .08 for x in closes]
    lows = [x - .08 for x in closes]
    volumes = [1200] * n
    return pd.DataFrame({
        "Open": opens, "High": highs,
        "Low": lows, "Close": closes, "Volume": volumes,
    }, index=days)


def test_breakout_volume_surges_with_prior_55day_pivot():
    bars = daily_bars()
    bars.loc[bars.index[-1], "Open"] = 11.2
    bars.loc[bars.index[-1], "Close"] = 12.5
    bars.loc[bars.index[-1], "High"] = 12.7
    bars.loc[bars.index[-1], "Low"] = 11.1
    bars.loc[bars.index[-1], "Volume"] = 3600
    a = daily_volume_breakout_shadow(bars)
    assert a["schema"] == SCHEMA
    assert a["available"] is True
    assert a["stage"] == "BREAKOUT_VOLUME_WATCH"
    assert a["breakout_above_prior_55d_high"] is True
    assert a["volume_spike"] is True
    assert a["volume_ratio_to_prior_20_median"] == 3.0
    assert a["previous_55d_high"] < a["last_close"]
    assert a["source_last_daily_bar"] == "2026-10-16"
    assert a["research_only"] is True
    assert a["options_execution_eligible"] is False
    assert a["independent_confirmation"] is False


def test_volume_surge_down_is_not_buy_signal():
    bars = daily_bars()
    bars.loc[bars.index[-1], "Close"] = 9.5
    bars.loc[bars.index[-1], "Low"] = 9.4
    bars.loc[bars.index[-1], "Open"] = 10
    bars.loc[bars.index[-1], "High"] = 10.1
    bars.loc[bars.index[-1], "Volume"] = 4800
    a = daily_volume_breakout_shadow(bars)
    assert a["stage"] == "HIGH_VOLUME_DOWN_RISK"
    assert a["volume_ratio_to_prior_20_median"] == 4.0


def test_price_only_breakout_never_claims_volume_confirmation():
    bars = daily_bars()
    bars.loc[bars.index[-1], ["Open", "High", "Low", "Close"]] = [
        11.2, 12.7, 11.1, 12.5,
    ]
    a = daily_volume_breakout_shadow(bars)
    assert a["stage"] == "BREAKOUT_PRICE_ONLY"
    assert a["volume_spike"] is False


def test_previous_day_breakout_retest_uses_prior_pivot():
    bars = daily_bars()
    yesterday = bars.index[-2]
    today = bars.index[-1]
    bars.loc[yesterday, ["Open", "High", "Low", "Close"]] = [
        11.1, 12.4, 11.0, 12.2,
    ]
    bars.loc[today, ["Open", "High", "Low", "Close"]] = [
        12.15, 12.25, 11.1, 12.15,
    ]
    a = daily_volume_breakout_shadow(bars)
    assert a["retest_hold"] is True
    assert a["breakout_above_prior_55d_high"] is False
    assert a["stage"] == "RETEST_HOLD_WATCH"


def test_malformed_short_unsorted_and_zero_reference_volume_fail_closed():
    short = daily_bars(69)
    assert daily_volume_breakout_shadow(short)["stage"] == "INSUFFICIENT"
    df = daily_bars()
    df.loc[df.index[-18:], "Volume"] = 0
    assert daily_volume_breakout_shadow(df)["stage"] == "INSUFFICIENT"
    invalid = daily_bars()
    invalid.loc[invalid.index[-1], "High"] = -2
    assert daily_volume_breakout_shadow(invalid)["available"] is False
    assert daily_volume_breakout_shadow(daily_bars().iloc[::-1])["available"] is False
    assert daily_volume_breakout_shadow(daily_bars().reset_index(drop=True))["available"] is False
    assert daily_volume_breakout_shadow(pd.DataFrame())["available"] is False


def test_integration_uses_completed_daily_bars_without_option_authority():
    day = daily_bars()
    day.loc[day.index[-1], ["Open", "High", "Low", "Close", "Volume"]] = [
        11.2, 12.7, 11.1, 12.5, 3600,
    ]
    # Live NY session: today's still-forming daily bar is always excluded.
    item = pack_symbol("RGC", day, None, None,
                       now=datetime.fromisoformat("2026-10-16T15:30:00-04:00"))
    assert item is not None
    val = item["volume_breakout_shadow"]
    assert val["source_last_daily_bar"] == "2026-10-15"
    assert val["stage"] in STAGES and val["stage"] != "BREAKOUT_VOLUME_WATCH"
    assert item["options_execution_grade"] is False
    assert val["options_execution_eligible"] is False


def test_six_month_history_is_requested_for_70_daily_bar_vcp_minimum():
    from pathlib import Path

    src = Path("scripts/build_stock_watch_charts.py").read_text(encoding="utf-8")
    assert '(("1d", "6mo"), ("15m", "5d"), ("5m", "5d"))' in src
    assert '(("1d", "3mo"),' not in src
    js = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert 'ghazi.daily_volume_breakout_shadow.v1' in js
    assert "RETEST_HOLD_WATCH" in js
    assert "HIGH_VOLUME_DOWN_RISK" in js
    assert "volume_breakout_shadow" in js
