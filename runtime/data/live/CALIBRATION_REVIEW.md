# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **215/100**
- **Raw priced signals:** **229**
- **Five-day mature signals:** **195**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 6 | 6 | 5 | 0.0% | 0.0% | 100.0% | 0.25 | -69.24 |
| 70-79 | 94 | 94 | 89 | 20.2% | 7.9% | 75.3% | 19.04 | -81.02 |
| 60-69 | 129 | 129 | 121 | 6.6% | 5.0% | 87.6% | 47.95 | -75.39 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 91 | 9.9% | 85.7% | 49.64 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 53 | 20.8% | 77.4% | 18.02 |
| bearish EMA stack; MACD/RSI bearish momentum | 40 | 0.0% | 100.0% | 21.79 |
| bullish EMA stack | 16 | 0.0% | 75.0% | 41.62 |
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
