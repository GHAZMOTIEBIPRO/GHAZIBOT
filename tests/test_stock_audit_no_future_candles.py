"""No future information in historical 5-minute stock outcome checkpoints."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.stock_outcome_backfill import evaluate_stock_event_from_bars

SIGNAL = datetime(2026, 10, 16, 14, 30, tzinfo=timezone.utc)


def event():
    return {
        "signal_id": "no-lookahead", "symbol": "TEST",
        "signal_time": SIGNAL.isoformat(), "direction": "up",
        "entry_price": 100.0, "follow_through_target_pct": 6.0,
        "failure_threshold_pct": 6.0,
    }


def bars(marks):
    return pd.DataFrame(
        {
            "Open": [100.0 for _ in marks],
            "High": [h for _,h,_ in marks],
            "Low": [l for _,_,l in marks],
            "Close": [100.0 for _ in marks],
            "Volume": [100 for _ in marks],
        },
        index=pd.DatetimeIndex([SIGNAL+timedelta(minutes=m) for m,_,_ in marks]),
    )


def test_checkpoint_reads_close_only_when_candle_has_completed():
    feed=bars([(0,101,99),(5,101,99),(10,101,99),(15,101,99),(60,101,99)])
    output=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=20))
    close=output["checkpoints"]["15m"]
    assert close["observed_at"]==(SIGNAL+timedelta(minutes=15)).isoformat()
    assert close["source_bar_start_at"]==(SIGNAL+timedelta(minutes=10)).isoformat()
    assert close["lag_minutes"]==0
    assert close["coverage_qualified"] is True
    assert "60m" not in output["checkpoints"]
    assert output["measurement_policy"]["measurement_version"]==2


def test_unfinished_bar_high_cannot_be_future_success():
    feed=bars([(0,101,99),(5,107,99)])
    out=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=7))
    assert out["audit_status"]=="pending"  # 5m candle starting +5 is not closed yet
    assert out["audit_terminal_at"] is None
    assert "15m" not in out["checkpoints"]
    later=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=10))
    assert later["audit_status"]=="success"
    bar=later["audit_terminal_bar"]
    assert later["audit_terminal_at"]==(SIGNAL+timedelta(minutes=10)).isoformat()
    assert bar["bar_start_at"]==(SIGNAL+timedelta(minutes=5)).isoformat()
    assert bar["bar_end_at"]==later["audit_terminal_at"]
    assert bar["touch_time_precision"]=="UNKNOWN_WITHIN_5M_CANDLE"


def test_do_not_sample_close_from_ongoing_bar_at_checkpoint():
    feed=bars([(0,101,99),(15,101,99)])
    out=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=17))
    assert "15m" not in out["checkpoints"]
    later=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=20))
    assert later["checkpoints"]["15m"]["observed_at"]==(
        SIGNAL+timedelta(minutes=20)
    ).isoformat()
    assert later["checkpoints"]["15m"]["lag_minutes"]==5


def test_same_candle_dual_touch_is_not_promoted_to_profit():
    both=bars([(0,107,93)])
    out=evaluate_stock_event_from_bars(event(),both,now=SIGNAL+timedelta(minutes=5))
    assert out["audit_status"]=="ambiguous"
    assert out["measurement_policy"]["intrabar_order_claimed"] is False
    assert out["audit_terminal_bar"]["touch_time_precision"]=="UNKNOWN_WITHIN_5M_CANDLE"


def test_provider_bar_after_now_never_has_coverage():
    feed=bars([(10,101,99),(60,101,99)])
    out=evaluate_stock_event_from_bars(event(),feed,now=SIGNAL+timedelta(minutes=12))
    assert out["audit_status"]=="unavailable"
    assert out["audit_reason"]=="no_post_signal_5m_bars"
