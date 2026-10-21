"""Closed daily VCP/trend research: no lookahead, no extra market-data request."""
from datetime import datetime

import pandas as pd

from options_radar.vcp_minervini_shadow import STAGES, vcp_trend_shadow
from scripts.build_stock_watch_charts import pack_symbol

NY = "America/New_York"


def bars():
    idx = pd.bdate_range(end="2026-10-16", periods=95, tz=NY)
    rows = []
    for i in range(95):
        close = 12.0 + i * 0.03
        radius = 0.42 if i < 77 else 0.10
        volume = 1100 if i < 85 else 120
        rows.append([close - 0.02, close + radius, close - radius, close, volume])
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def test_detects_minervini_style_trend_and_vcp_volume_contraction():
    research = vcp_trend_shadow(bars())
    assert research["available"] is True
    assert research["stage"] == "TIGHT_WATCH"
    assert research["ema_stack"] is True
    assert research["near_55d_high"] is True
    assert research["atr_contraction"] is True
    assert research["volume_dry_up"] is True
    assert research["atr_ratio"] < 0.85 and research["volume_ratio"] < 0.85
    assert research["research_only"] is True
    assert research["independent_confirmation"] is False
    assert research["option_execution_eligible"] is False
    assert research["source_last_daily_bar"] == "2026-10-16"


def test_volume_without_atr_contraction_is_not_tight():
    df = bars()
    df.loc[df.index[-14:], "High"] += 1.0
    df.loc[df.index[-14:], "Low"] -= 1.0
    result = vcp_trend_shadow(df)
    assert result["stage"] != "TIGHT_WATCH"
    assert result["atr_contraction"] is False


def test_no_short_or_malformed_historical_series_can_be_a_signal():
    assert vcp_trend_shadow(bars().iloc[-30:])["stage"] == "INSUFFICIENT"
    invalid = bars()
    invalid.loc[invalid.index[-2], "Close"] = -1.0
    assert vcp_trend_shadow(invalid)["stage"] == "INSUFFICIENT"
    invalid = bars()
    invalid.loc[invalid.index[-1], "Volume"] = float("nan")
    assert vcp_trend_shadow(invalid)["stage"] == "INSUFFICIENT"
    assert vcp_trend_shadow(pd.DataFrame())["stage"] == "INSUFFICIENT"
    assert vcp_trend_shadow(bars().reset_index(drop=True))["stage"] == "INSUFFICIENT"


def test_history_is_completed_before_shadow_and_never_promotes_call_put():
    original = bars()
    now = datetime.fromisoformat("2026-10-16T15:45:00-04:00")
    item = pack_symbol("RGC", original, None, None, now=now)
    # The close of today's daily bar is not known at this intraday time.
    assert item is not None
    shadow = item["vcp_minervini_shadow"]
    assert shadow["source_last_daily_bar"] == "2026-10-15"
    assert shadow["stage"] in STAGES
    assert item["options_execution_grade"] is False
    assert shadow["option_execution_eligible"] is False
