# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase3`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **106/100**
- **Raw priced signals:** **172**
- **Five-day mature signals:** **0**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | 0 | — | — | — | — | — |
| 70-79 | 55 | 55 | 22 | 18.2% | 18.2% | 0.0% | 10.97 | -12.92 |
| 60-69 | 117 | 117 | 84 | 32.1% | 22.6% | 1.2% | 14.44 | -12.75 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 57 | 31.6% | 1.8% | 16.19 |
| bearish EMA stack; MACD/RSI bearish momentum | 25 | 20.0% | 0.0% | 10.93 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 17 | 17.6% | 0.0% | 9.36 |
| bullish EMA stack | 7 | 71.4% | 0.0% | 14.18 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
