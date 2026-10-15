# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **223/100**
- **Raw priced signals:** **241**
- **Five-day mature signals:** **197**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 6 | 6 | 5 | 0.0% | 0.0% | 100.0% | 0.25 | -78.09 |
| 70-79 | 98 | 98 | 91 | 19.8% | 7.7% | 75.8% | 18.65 | -83.62 |
| 60-69 | 135 | 135 | 125 | 7.2% | 4.8% | 85.6% | 46.94 | -74.54 |
| 0-59 | 2 | 2 | 2 | 0.0% | 0.0% | 0.0% | 36.35 | -0.64 |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 94 | 9.6% | 83.0% | 48.06 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 54 | 22.2% | 75.9% | 18.89 |
| bearish EMA stack; MACD/RSI bearish momentum | 42 | 0.0% | 95.2% | 22.48 |
| bullish EMA stack | 18 | 0.0% | 83.3% | 37.16 |
| Secondary mention — Acquisition | 6 | 100.0% | 0.0% | -0.84 |
| bullish EMA stack; 20-day breakout with relative volume; MACD/RSI bullish moment | 4 | 0.0% | 100.0% | -0.01 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 185.53 |
| FDA approval | 2 | 0.0% | 100.0% | 57.30 |
| bearish EMA stack | 1 | 0.0% | 100.0% | 7.68 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
