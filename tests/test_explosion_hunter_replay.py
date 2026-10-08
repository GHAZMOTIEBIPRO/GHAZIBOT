import numpy as np
import pandas as pd

from scripts.replay_explosion_lab import build_replay_frame, evaluate_replay


def test_100_percent_target_does_not_relabel_25_percent_move():
    dates = pd.date_range("2025-01-01", periods=45, freq="B")
    closes = np.full(45, 10.0)
    closes[35] = 13.0
    frame = pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": np.full(45, 10000),
    }, index=dates)
    replay = build_replay_frame(frame, target_return_pct=100)
    assert not bool(replay.loc[dates[34], "explosion_label"])
    assert pd.isna(replay.iloc[-1]["future_5d_max_return_pct"])
    assert evaluate_replay(replay)["rows"] <= 40


def test_100_percent_target_detects_110_percent_forward_close():
    dates = pd.date_range("2025-01-01", periods=45, freq="B")
    closes = np.full(45, 10.0)
    closes[35:] = 21.0
    frame = pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": np.full(45, 10000),
    }, index=dates)
    replay = build_replay_frame(frame, target_return_pct=100)
    assert bool(replay.loc[dates[34], "explosion_label"])
