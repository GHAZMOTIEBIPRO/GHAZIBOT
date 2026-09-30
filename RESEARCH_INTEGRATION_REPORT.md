"""Research and integration report for BLACK BOX signal generation.

This document intentionally distinguishes research-only sources from feeds that
may receive decision authority. Exchange-grade real-time options data generally
requires a licensed provider; free tiers must be treated as research until the
validator proves source, freshness, and quote quality.
"""

# BLACK BOX R&D INTEGRATION REPORT

## Recommended components

| Capability | Candidate | Integration decision |
|---|---|---|
| GEX / gamma levels | [GammaGrid](https://github.com/gammagrid/gammagrid), [gex-terminal](https://github.com/zrack/gex-terminal) | Use their formulas as research references; keep the calculation in an internal adapter so provider licensing and sign conventions are explicit. |
| Options flow / unusual activity | [KPH3802/options-volume-scanner](https://github.com/KPH3802/options-volume-scanner), [Market Profile](https://github.com/ilyakg/market_profile) | Reuse anomaly concepts only. The scanner uses Yahoo data and therefore cannot grant decision authority in this project. |
| Technical analysis | [pandas-ta](https://github.com/twopirllc/pandas-ta), [TA-Lib](https://github.com/TA-Lib/ta-lib) | The first implementation uses dependency-free EMA/RSI calculations. pandas-ta or TA-Lib can be added behind an adapter later. |
| Market data | Finnhub, IEX Cloud, Polygon, Interactive Brokers | Use an injected provider adapter. A free plan is not automatically real-time or licensed for options; every quote must carry lineage and timestamp. |
| Backtesting | [QuantConnect Lean](https://github.com/QuantConnect/Lean) | Research/backtesting only; never promote backtest output to a live alert without fresh quote validation. |

## Safety boundaries

1. `yfinance`, Yahoo, delayed, indicative, and reconstructed quotes are always
   research-only. They cannot produce `decision_authority=True`.
2. A signal is emitted only after `validators/options_validator.py` approves the
   quote and the SEC verifier confirms the issuer with confidence at least 0.85.
3. GEX and flow are evidence, not proof of a squeeze or institutional intent.
   The alert labels them as catalysts and includes the source lineage.
4. The engine does not place orders. It produces a manual-review Telegram alert.
5. 0DTE is allowed only when the caller explicitly supplies a valid same-day
   expiry and a live, fresh quote; otherwise the engine selects weekly/monthly
   according to the supplied expiry candidates.

## Proposed data contract

Providers should return normalized dictionaries with `symbol`, `bid`, `ask`,
`last`, `quote_timestamp`, `source`, `contract_type`, `strike`, `expiration`,
`underlying_price`, and optional `gex`, `flow`, `volume`, and `open_interest`.
The signal generator is deliberately provider-agnostic and never imports
`yfinance`.

## Rollout plan

1. Run the engine with recorded fixtures and no Telegram credentials.
2. Add contract tests for each licensed provider adapter.
3. Replay at least 30 sessions and measure false positives, stale quotes, and
   duplicate-alert behavior.
4. Enable Telegram delivery only after provider entitlement and SEC rate-limit
   compliance are verified.
