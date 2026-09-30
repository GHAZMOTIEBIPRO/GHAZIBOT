# BLACK BOX Open-Source Integrations

## Implemented

### `vollib/py_vollib`

- Project: https://github.com/vollib/pyvollib
- Package: `py-vollib`
- Integration point: `options_radar/opensource_pricing.py`
- Used by: `options_radar/scoring.py`
- Purpose: independent Black-Scholes delta/gamma calculation for screening.
- Safety: optional adapter; BLACK BOX retains the native local formula if the package is unavailable or rejects an input.
- Limitation: this is a pricing/math library, not a market-data provider and not an execution source.

### `dhawalc/spx-gamma-levels`

- Project: https://github.com/dhawalc/spx-gamma-levels
- Existing integration point: `options_radar/spx_external_gamma.py`
- Purpose: read-only SPX gamma context such as gamma flip and call/put levels.
- Safety: treated as contextual research evidence; it does not create execution authority.

## Deferred intentionally

### VectorBT

- Project: https://github.com/polakowo/vectorbt
- Intended use: offline research and walk-forward validation only.
- Not added to production requirements because it is not a data provider and would enlarge the runtime dependency footprint.

### QuantLib

- Project: https://github.com/lballabio/QuantLib
- Intended use: advanced derivatives valuation and scenario testing.
- Deferred until BLACK BOX has a verified live options source; better math cannot repair stale or unofficial quotes.

### LEAN / NautilusTrader

- Projects:
  - https://github.com/QuantConnect/Lean
  - https://github.com/nautechsystems/nautilus_trader
- Intended use: a future research/execution architecture.
- Not embedded into the current GitHub Actions bot because replacing the existing guarded pipeline would create a large, high-risk rewrite.

## Data-quality rule

Open-source code does not automatically make data production-ready. BLACK BOX keeps these distinctions:

- Math library: validates calculations only.
- Research library: validates strategies only.
- Market-data provider: supplies quotes/bars and must pass freshness/source gates.
- Execution provider: must separately pass live entitlement, NBBO/trade-flow, and delivery gates.

No integration above changes `decision_authority` or upgrades Yahoo/YFinance fallback data to execution-ready data.
