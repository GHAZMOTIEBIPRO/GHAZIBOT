# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **230/100**
- **Raw priced signals:** **243**
- **Five-day mature signals:** **203**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 6 | 6 | 5 | 0.0% | 0.0% | 100.0% | 0.25 | -79.53 |
| 70-79 | 98 | 98 | 94 | 19.1% | 7.4% | 76.6% | 18.31 | -83.15 |
| 60-69 | 136 | 136 | 129 | 7.0% | 4.7% | 85.3% | 46.76 | -73.95 |
| 0-59 | 3 | 3 | 2 | 0.0% | 0.0% | 0.0% | 44.64 | -3.78 |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 95 | 9.5% | 85.3% | 47.63 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 59 | 20.3% | 69.5% | 20.34 |
| bearish EMA stack; MACD/RSI bearish momentum | 42 | 0.0% | 95.2% | 22.87 |
| bullish EMA stack | 18 | 0.0% | 94.4% | 37.16 |
| Secondary mention — Acquisition | 6 | 100.0% | 0.0% | -0.84 |
| bullish EMA stack; 20-day breakout with relative volume; MACD/RSI bullish moment | 4 | 0.0% | 100.0% | -0.01 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 185.53 |
| FDA approval | 2 | 0.0% | 100.0% | 57.30 |
| bearish EMA stack | 1 | 0.0% | 100.0% | 7.68 |
| Clinical trial registry update | 1 | 0.0% | 100.0% | 1.21 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
