"""Independent reference check of the engine's Black-Scholes Greeks.

`blackscholes` (MIT, CarloLepelaars/blackscholes, pure Python) is a
development-only oracle; the production engine does not import it.
"""
import math

import pytest

from options_radar.ghazi_gex_multi import gamma_bs, greeks_bs

reference = pytest.importorskip("blackscholes")

GRID = [(S, K, T, sigma)
        for S in (90.0, 100.0, 110.0, 7690.0)
        for K in (95.0, 100.0, 105.0, 7700.0)
        for T in (0.002, 0.05, 0.5)
        for sigma in (0.15, 0.4)
        if (S > 1000) == (K > 1000)]


@pytest.mark.parametrize("name", ["delta", "gamma", "vega", "vanna", "charm", "vomma", "zomma"])
def test_engine_greeks_match_independent_reference(name):
    for S, K, T, sigma in GRID:
        ours = greeks_bs(S, K, sigma, T)[name]
        ref = getattr(reference.BlackScholesCall(S=S, K=K, T=T, r=0.0, sigma=sigma, q=0.0), name)()
        assert ours == pytest.approx(ref, rel=1e-9, abs=1e-12), (name, S, K, T, sigma)


def test_gex_gamma_matches_reference():
    for S, K, T, sigma in GRID:
        ref = reference.BlackScholesCall(S=S, K=K, T=T, r=0.0, sigma=sigma, q=0.0).gamma()
        assert math.isclose(gamma_bs(S, K, sigma, T), ref, rel_tol=1e-9, abs_tol=1e-15)
