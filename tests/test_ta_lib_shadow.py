from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from options_radar.ta_lib_shadow import TALibUnavailable, calculate_shadow


def _history(rows: int = 80) -> pd.DataFrame:
    close = np.linspace(100.0, 120.0, rows)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(rows, 100_000.0),
        }
    )


def test_shadow_rejects_missing_and_invalid_ohlcv() -> None:
    with pytest.raises(ValueError, match="Missing OHLCV"):
        calculate_shadow(_history().drop(columns=["Volume"]))
    invalid = _history()
    invalid.loc[0, "High"] = np.nan
    with pytest.raises(ValueError, match="missing or non-numeric"):
        calculate_shadow(invalid)
    invalid = _history()
    invalid.loc[0, "High"] = 1.0
    invalid.loc[0, "Low"] = 2.0
    with pytest.raises(ValueError, match="High below Low"):
        calculate_shadow(invalid)


def test_shadow_returns_finite_reference_values_when_talib_is_available() -> None:
    try:
        snapshot = calculate_shadow(_history())
    except TALibUnavailable:
        pytest.skip("optional TA-Lib dependency is not installed")
    assert snapshot.source == "TA-Lib"
    assert snapshot.rows == 80
    floats = (value for value in snapshot.__dict__.values() if isinstance(value, float))
    assert all(np.isfinite(value) for value in floats)


def test_shadow_rejects_short_history_before_optional_import() -> None:
    with pytest.raises(ValueError, match="Not enough OHLCV"):
        calculate_shadow(_history(20))
