import numpy as np
import pandas as pd

from scripts.replay_explosion_lab import build_replay_frame, evaluate_replay


def _history(rows: int = 70) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=rows, freq="B")
    close = np.linspace(5.0, 5.8, rows)
    volume = np.full(rows, 100_000.0)
    volume[-8:] = [120_000, 150_000, 220_000, 380_000, 700_000, 1_300_000, 2_200_000, 3_000_000]
    close[-5:] = [5.9, 6.2, 7.0, 8.4, 10.2]
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def test_replay_score_does_not_change_when_only_future_prices_change():
    history = _history()
    first = build_replay_frame(history)
    cutoff = history.index[-12]

    changed = history.copy()
    future_mask = changed.index > cutoff
    changed.loc[future_mask, ["Open", "High", "Low", "Close"]] *= 5.0
    second = build_replay_frame(changed)

    assert np.isclose(first.loc[cutoff, "replay_score"], second.loc[cutoff, "replay_score"], equal_nan=True)


def test_replay_evaluator_reports_forward_explosion_windows():
    frame = build_replay_frame(_history())
    metrics = evaluate_replay(frame, threshold=55)
    assert metrics["rows"] > 20
    assert metrics["positive_windows"] > 0
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0
