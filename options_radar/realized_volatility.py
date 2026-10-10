from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _series(frame: pd.DataFrame, name: str) -> pd.Series:
    for candidate in (name, name.capitalize()):
        if candidate in frame:
            return pd.to_numeric(frame[candidate], errors="coerce")
    return pd.Series(dtype="float64")


def yang_zhang_realized_volatility(
    history: pd.DataFrame | None,
    *,
    window: int = 30,
    trading_days: int = 252,
) -> float | None:
    """Annualized Yang-Zhang realized volatility from completed daily OHLC bars.

    Independent implementation of the published estimator. It is used only as
    research context for long-option value grading and never creates a quote.
    """

    if history is None or history.empty or window < 3:
        return None

    open_ = _series(history, "open")
    high = _series(history, "high")
    low = _series(history, "low")
    close = _series(history, "close")
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=history.index,
    ).dropna()
    frame = frame[
        (frame["open"] > 0)
        & (frame["high"] > 0)
        & (frame["low"] > 0)
        & (frame["close"] > 0)
    ]
    if len(frame) < 4:
        return None

    use = frame.tail(window + 1)
    previous_close = use["close"].shift(1)
    working = use.iloc[1:].copy()
    previous_close = previous_close.iloc[1:]
    if len(working) < 3:
        return None

    overnight = (working["open"] / previous_close).map(math.log)
    open_close = (working["close"] / working["open"]).map(math.log)
    up = (working["high"] / working["open"]).map(math.log)
    down = (working["low"] / working["open"]).map(math.log)
    rs = up * (up - open_close) + down * (down - open_close)

    n = len(working)
    if n < 2:
        return None
    var_overnight = float(overnight.var(ddof=1))
    var_open_close = float(open_close.var(ddof=1))
    var_rs = float(rs.mean())
    if not all(math.isfinite(value) for value in (var_overnight, var_open_close, var_rs)):
        return None

    k = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
    variance = var_overnight + k * var_open_close + (1.0 - k) * var_rs
    if variance <= 0 or not math.isfinite(variance):
        returns = (use["close"] / use["close"].shift(1)).dropna().map(math.log)
        if len(returns) < 2:
            return None
        fallback_variance = float(returns.var(ddof=1))
        if fallback_variance <= 0 or not math.isfinite(fallback_variance):
            return None
        variance = fallback_variance

    return math.sqrt(variance * float(trading_days))


def realized_volatility_context(
    history: pd.DataFrame | None,
    *,
    window: int = 30,
) -> dict[str, Any]:
    value = yang_zhang_realized_volatility(history, window=window)
    return {
        "available": value is not None,
        "method": "YANG_ZHANG",
        "window_sessions": window,
        "annualized_volatility": round(value, 6) if value is not None else None,
        "research_only": True,
        "decision_authority": False,
    }
