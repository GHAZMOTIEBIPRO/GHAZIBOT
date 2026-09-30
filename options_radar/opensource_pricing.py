from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def vollib_black_scholes_delta_gamma(
    *,
    spot: float,
    strike: float,
    t_years: float,
    volatility: float,
    risk_free_rate: float,
    option_type: str,
) -> tuple[float, float, str] | None:
    """Use vollib/py_vollib for a second implementation of delta and gamma.

    The adapter is deliberately optional. If the dependency is absent or rejects
    an input, callers continue with BLACK BOX's local screening approximation.
    This is a math-validation bridge, not a market-data or execution provider.
    """
    values = [spot, strike, t_years, volatility]
    if any(_finite(value) is None or float(value) <= 0 for value in values):
        return None
    flag = str(option_type or "").strip().lower()[:1]
    if flag not in {"c", "p"}:
        return None
    try:
        from vollib.black_scholes.greeks.analytical import delta, gamma

        result_delta = delta(
            flag,
            float(spot),
            float(strike),
            float(t_years),
            float(risk_free_rate),
            float(volatility),
        )
        result_gamma = gamma(
            flag,
            float(spot),
            float(strike),
            float(t_years),
            float(risk_free_rate),
            float(volatility),
        )
    except (ArithmeticError, ImportError, TypeError, ValueError):
        return None
    parsed_delta = _finite(result_delta)
    parsed_gamma = _finite(result_gamma)
    if parsed_delta is None or parsed_gamma is None:
        return None
    return parsed_delta, parsed_gamma, "vollib_black_scholes"
