# GHAZIMOTIEB OPENING FIB Ω — empirical exploratory audit 2026-11-15

**Status: RESEARCH_ONLY / NEGATIVE_EXPLORATORY_RESULT / NOT_EMPIRICALLY_VALIDATED.**

## Source and methodology

Private, authorized connected-account Alpaca historical **SIP** 5-minute bars for SPY and QQQ, requested in 11 bounded calendar-month queries from January 1 through November 14, 2026. The sample spans **219 distinct U.S. trading days, January 2 to November 13, 2026**. No proprietary candle-level data or account credentials were committed or reproduced.

The retrieval yielded 84,049 bars including outside regular market hours; 49,885 outside 09:30–16:00 America/New_York were discarded. There were 438 symbol-day groups of either 78 regular-session or 42 early-close candles, in five-minute order without duplicate timestamps under the filter. No price adjustments, corporate-action reconciliation, cross-vendor reconciliation or session-calendar confirmation of every 42-bar day was carried out. This is a **limited two-ETF sample**, not a comprehensive, execution-grade validation.

The independent evaluation was implemented in JavaScript to consume the connected Alpaca tool response directly. It reproduces the six prototype models and the 5/10/15/30/60-minute windows, and applies three level families for 90 parameter groups. **The placebo hash differs from the SHA-256 used by Python**. Therefore do not present these figures as a bit-for-bit execution of the Python laboratory; trade-level agreement with the packaged Python and Pine scripts remains to be checked. Opening levels become available after the opening window. Signals use candle closes and enter at the next candle open, with 12 basis points hypothetical round-trip costs on the underlying, stop-first if stop and target both touch. These are research assumptions and are not actual fill observations.

Days were split chronologically into **109 training**, **55 validation**, and **55 sealed final test** days. The final 55 days were not opened or used for parameter choice. 58 of 90 grid cells had at least 30 training trades. The highest training mean net R among them was *negative* at -0.3842 R for 30m Multi-Timeframe Alignment with equal/ordinary levels.

## Validation results (held out from training, but NOT final holdout)

| Predefined model | Validation trades | Win rate | Mean net R | Profit factor |
|---|---:|---:|---:|---:|
| 15m ORB with Fibonacci targets | 52 | 28.8% | -1.0520 | 0.219 |
| 15m ORB with ordinary/equal targets | 51 | 29.4% | -1.0438 | 0.233 |
| 15m Retest with Fibonacci targets | 38 | 26.3% | -1.3405 | 0.111 |
| Best on training only: 30m MTF with equal levels | 26 | 30.8% | -0.8218 | 0.268 |

R is price-based net reward divided by initial price-distance to stop, *not* account return, option premium return, realized P&L, or calibrated likelihood.

**Interpretation:** No edge was found in this first prototype. Fibonacci targets did not outperform the ordinary levels in the predefined 15-minute ORB comparison. This is not a universal proof against opening-range methods or Fibonacci; it describes this prototype and period.

## Independent structural audit and correction

The archived Python v1 Fibonacci Reversal model used an opening-range-wide stop yet sought the opposite boundary as target 2, while demanding a risk/reward ratio at least 1.5. That combination prevented reversal trades in this experiment. In source v1.1 the reversal stop is computed from the lowest/highest *already closed* reversal candles plus a 0.08 range margin, so risk/reward is not geometrically precluded. The field `signal_at_utc` is also corrected from the signal candle start to its close (+5 minutes), with fill still at next-bar open. Both changes are covered by synthetic regression tests.

These source fixes **invalidate extrapolation of the v1 Fibonacci Reversal performance**. The 219-day experiment was not repeated through Python v1.1. Tests check logic only; Pine v6 was not officially compiled in TradingView. No options prices, executable spread, Greeks, or 0DTE fill audit were performed.

## Required before any trading decision

Use a documented source/provenance manifest and ensure licensing. Replicate an exact 5-minute candle sample bar-for-bar and trade-for-trade in Python, rerun all models after fixing the reversal definition, verify point-in-time source properties and early closures, test trading costs 12/25/50 bps and session/event regimes, then freeze model rules before unsealing final holdout. Real contracts need independent contract bid/ask histories; indicator signals alone cannot establish CALL/PUT returns.

Sources:
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://docs.alpaca.markets/us/reference/stockbars
- https://docs.alpaca.markets/us/docs/historical-stock-data-1


## Additional v1.1 reversal replay: still an independent JavaScript check

After correcting the source-level stop geometry, the same SIP dates were retrieved again and the revised **15-minute Fibonacci Reversal** rule independently re-evaluated. No final 55-day holdout results were computed.

| Level family; assumed round-trip cost | Training trades / mean R | Validation trades | Validation win rate | Validation mean net R | Validation PF |
|---|---:|---:|---:|---:|---:|
| Fib / 12bps | 32 / -0.6100 | 25 | 24.0% | -1.2265 | 0.163 |
| Equal / 12bps | 25 / -0.9775 | 23 | 21.7% | -1.3626 | 0.125 |
| Fib / 25bps | 32 / -1.6122 | 25 | 12.0% | -2.2982 | 0.027 |
| Fib / 50bps | 32 / -3.5396 | 25 | 0.0% | -4.3591 | 0.000 |

This additional run supports **a negative result for the revised reversal prototype at these assumed costs**. Although the Fib variant was less negative than the equal-level variant in this particular sample, neither was profitable and the sample is far too small for a conclusion that Fibonacci adds a robust edge. This independent replay still has no transaction-by-transaction verification in the Python CLI and is not an options execution backtest.
