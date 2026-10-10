import numpy as np
import pandas as pd

from options_radar.realized_volatility import (
    realized_volatility_context,
    yang_zhang_realized_volatility,
)


def _history() -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=80, freq="B", tz="UTC")
    base = 100.0 + np.linspace(0, 12, 80)
    overnight = np.sin(np.linspace(0, 8, 80)) * 0.8
    open_ = base + overnight
    close = open_ + np.sin(np.linspace(0, 18, 80)) * 1.2
    high = np.maximum(open_, close) + 1.1
    low = np.minimum(open_, close) - 1.0
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
        },
        index=index,
    )


def test_yang_zhang_realized_volatility_is_finite_and_positive():
    value = yang_zhang_realized_volatility(_history(), window=30)

    assert value is not None
    assert 0 < value < 2.0


def test_realized_volatility_context_is_research_only():
    context = realized_volatility_context(_history(), window=30)

    assert context["available"] is True
    assert context["method"] == "YANG_ZHANG"
    assert context["research_only"] is True
    assert context["decision_authority"] is False


def test_realized_volatility_fails_closed_on_short_history():
    assert yang_zhang_realized_volatility(_history().head(3), window=30) is None
