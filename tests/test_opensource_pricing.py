from __future__ import annotations

import math

from options_radar.opensource_pricing import vollib_black_scholes_delta_gamma
from options_radar.scoring import approximate_greeks


def test_vollib_adapter_returns_finite_call_greeks_when_available() -> None:
    result = vollib_black_scholes_delta_gamma(
        spot=100.0,
        strike=100.0,
        t_years=0.5,
        volatility=0.2,
        risk_free_rate=0.04,
        option_type="call",
    )
    if result is None:
        return
    delta, gamma, provenance = result
    assert 0.0 < delta < 1.0
    assert gamma > 0.0
    assert provenance == "vollib_black_scholes"


def test_approximate_greeks_remains_finite_with_open_source_bridge() -> None:
    delta, gamma = approximate_greeks(100.0, 100.0, 0.5, 0.2, 0.04, "call")
    assert math.isfinite(delta)
    assert math.isfinite(gamma)
    assert 0.0 < delta < 1.0
    assert gamma > 0.0


def test_invalid_pricing_inputs_fail_closed() -> None:
    assert vollib_black_scholes_delta_gamma(
        spot=0.0,
        strike=100.0,
        t_years=0.5,
        volatility=0.2,
        risk_free_rate=0.04,
        option_type="call",
    ) is None
