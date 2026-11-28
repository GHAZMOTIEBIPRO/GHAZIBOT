"""Black-76 model Greeks for European index options on a forward (SPXW / NDXP weeklies).

Owner (PHASE 5): index weeklies are European and cash-settled, and the cash index is not available
here, so they are valued on the put-call-parity implied forward (options_radar.parity_reference),
never on SPY/QQQ or a "cash index" estimate. Implied volatility is solved from the indicative mid.
The outputs are MODEL Greeks, not official values and not OPRA. Undiscounted per-unit sensitivities
per share of the index (multiplier 100 applies to cost, not to these numbers); theta per calendar day,
vega per 1 vol point. Refuses when an input is missing or out of range (no fabricated number).
"""
from __future__ import annotations

from math import erf, exp, log, pi, sqrt
from typing import Any

SOURCE = "model_black76_forward"


def _n(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2 * pi)


def _cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


def price(f: float, k: float, t: float, sigma: float, r: float, call: bool) -> float:
    d1 = (log(f / k) + 0.5 * sigma * sigma * t) / (sigma * sqrt(t))
    d2 = d1 - sigma * sqrt(t)
    df = exp(-r * t)
    return df * (f * _cdf(d1) - k * _cdf(d2)) if call else df * (k * _cdf(-d2) - f * _cdf(-d1))


def implied_vol(premium: float, f: float, k: float, t: float, r: float, call: bool) -> float | None:
    """Bisection on [0.5%, 500%]; None when the premium is outside the no-arbitrage range."""
    df = exp(-r * t)
    intrinsic = df * max(f - k, 0.0) if call else df * max(k - f, 0.0)
    upper = df * (f if call else k)
    if not (intrinsic < premium < upper):
        return None
    lo, hi = 0.005, 5.0
    if not (price(f, k, t, lo, r, call) <= premium <= price(f, k, t, hi, r, call)):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if price(f, k, t, mid, r, call) < premium:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def greeks(*, premium: float | None, forward: float | None, strike: float, years: float, rate: float,
           call: bool) -> dict[str, Any]:
    if not premium or not forward or premium <= 0 or forward <= 0 or strike <= 0 or years <= 0:
        return {"status": "INPUT_MISSING", "source": SOURCE}
    sigma = implied_vol(premium, forward, strike, years, rate, call)
    if sigma is None:
        return {"status": "NO_IMPLIED_VOL", "source": SOURCE}
    sq = sqrt(years)
    d1 = (log(forward / strike) + 0.5 * sigma * sigma * years) / (sigma * sq)
    d2 = d1 - sigma * sq
    df = exp(-rate * years)
    delta = df * (_cdf(d1) if call else _cdf(d1) - 1)
    gamma = df * _n(d1) / (forward * sigma * sq)
    vega = df * forward * _n(d1) * sq / 100
    p = price(forward, strike, years, sigma, rate, call)
    theta_year = -df * forward * _n(d1) * sigma / (2 * sq) + rate * p
    return {"status": "OK", "source": SOURCE, "iv": round(sigma, 4), "delta": round(delta, 4),
            "gamma": round(gamma, 6), "vega": round(vega, 4), "theta": round(theta_year / 365, 4),
            "d2": round(d2, 4)}
