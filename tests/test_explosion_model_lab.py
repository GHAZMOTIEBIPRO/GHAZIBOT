import numpy as np
import pandas as pd
import pytest

from options_radar.explosion_model_lab import (
    HOLD,
    NOT_TESTABLE,
    collect,
    cost_pct,
    evaluate,
    features,
    outcome,
    summarize,
)


def bars_from(rows):
    idx = pd.bdate_range("2026-01-01", periods=len(rows))
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def flat(n, price=10.0, vol=200_000):
    return [[price, price * 1.01, price * 0.99, price, vol] for _ in range(n)]


def test_target_before_stop_with_next_open_entry_and_costs():
    rows = flat(10) + [[10, 10.2, 9.9, 10, 1e5], [10, 10.9, 9.9, 10.8, 1e5]] + flat(6)
    b = bars_from(rows)
    payoff, status = outcome(b, 9, "long")  # entry at open of bar 10 = 10.0
    assert status == "TARGET" and payoff == pytest.approx(8.0 - cost_pct(10.0))


def test_same_bar_target_and_stop_is_a_loss_never_a_win():
    rows = flat(10) + [[10, 11.0, 9.4, 10, 1e5]] + flat(6)
    payoff, status = outcome(bars_from(rows), 9, "long")
    assert status == "AMBIGUOUS_AS_LOSS" and payoff < 0


def test_short_side_and_timeout_use_close_after_hold():
    rows = flat(10) + [[10, 10.1, 9.8, 9.9, 1e5]] * HOLD + flat(3)
    payoff, status = outcome(bars_from(rows), 9, "short")
    assert status == "TIMEOUT"
    assert payoff == pytest.approx((1 - 9.9 / 10) * 100 - cost_pct(10.0))
    assert outcome(bars_from(flat(5)), 3, "long") is None  # not enough future bars


def test_features_are_causal_and_breakout_model_fires_once():
    rows = flat(70)
    rows[65] = [10, 12.5, 10, 12.4, 900_000]  # breakout above prior 20d high on 4.5x volume
    b = bars_from(rows)
    f = features(b, None)
    assert f["prior_high20"].iloc[65] == pytest.approx(10.1)  # excludes the breakout bar itself
    frame = collect({"AAA": pd.concat([b, bars_from(flat(20)).set_index(
        pd.bdate_range(b.index[-1] + pd.offsets.BDay(), periods=20))])}, None)
    fired = frame[frame["model"] == "BREAKOUT_VOLUME"]
    assert list(fired["date"]) == [b.index[65]]
    assert (frame["model"] == "BASELINE_ALL_DAYS").sum() > 10


def test_summary_breakeven_and_evaluate_reports_not_testable_models():
    g = pd.DataFrame({"symbol": ["A"] * 4, "status": ["TARGET", "STOP", "STOP", "TIMEOUT"],
                      "net": [7.4, -5.6, -5.6, 0.4]})
    s = summarize(g)
    assert s["target_hit_rate"] == 0.25 and s["breakeven_hit_rate"] == round(5 / 13, 4)
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2025-01-01", periods=80)
    frame = pd.DataFrame({"symbol": "A", "date": np.repeat(dates, 2),
                          "model": ["BASELINE_ALL_DAYS", "GAP_CONTINUATION"] * 80,
                          "net": rng.normal(0, 3, 160), "status": "TIMEOUT"})
    out = evaluate(frame)
    assert set(NOT_TESTABLE) <= set(out["models"])
    assert out["models"]["CATALYST_FLOAT"]["status"] == "NOT_TESTABLE"
    assert out["models"]["GAP_CONTINUATION"]["beats_baseline_both_halves_and_positive_late"] in (True, False)
    assert out["spa"]["status"] in {"OK", "ARCH_UNAVAILABLE"}
