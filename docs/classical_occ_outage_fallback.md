# OCC 520 incident: Cboe C1 reference fallback for classical stock direction

## Evidence
The main-branch classical radar on 2026-10-14 reported `occ:EU` and `occ:IU` HTTP 520, no OCC cache, zero officially verified companies and 0% data coverage. Failing closed correctly prevented all Telegram signals.

## Limited contingency
Only when OCC cannot verify optionability, the **underlying-only classical direction path** retrieves Cboe's official C1 underlying reference CSV:

`https://cdn.cboe.com/data/us/options/market_statistics/symbol_reference/cone-underlying.csv`

The file must have a parseable Symbol header, over 100 unique listed underlyings, and an explicit Last-Modified no older than seven calendar days. Otherwise the radar remains FAILED, with zero sent signals.

Cboe C1 is a **single exchange**, not the complete U.S. or OCC options universe. It is normally prior-business-day data, not a real-time contract listing or option quote. Only its explicitly listed stocks qualify for underlying-only CALL/PUT research. Every published row retains `optionability_verified_by_occ` and `optionability_verified_by_cboe` separately, plus a visible source label in Telegram.

**Not changed:** the V11 option execution gate, OCC contract identity, contract liquidity/freshness checks, OPRA rights, or contract recommendations. This fallback does not claim that a specific contract exists or has executable quotes.

## Recovery validation
Run the existing classical-direction-radar GitHub Actions workflow and inspect its `classical-direction-radar` artifact. On a legitimate Cboe fallback, `summary.cboe_optionability_verified` is true, `universe.cboe_last_modified` is within seven days, `universe.occ_errors` records OCC failures, and the resulting status is READY only if the price-data coverage gate also passes. A successful code/CI test is not proof of live Telegram delivery.
