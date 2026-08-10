# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **184/100**
- **Raw priced signals:** **192**
- **Five-day mature signals:** **173**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 1 | 1 | 1 | 0.0% | 0.0% | 0.0% | 2.12 | -73.15 |
| 70-79 | 72 | 72 | 69 | 5.8% | 5.8% | 0.0% | 21.71 | -79.43 |
| 60-69 | 119 | 119 | 114 | 25.4% | 18.4% | 0.9% | 46.31 | -72.22 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 73 | 27.4% | 1.4% | 54.24 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 51 | 5.9% | 0.0% | 18.65 |
| bearish EMA stack; MACD/RSI bearish momentum | 36 | 13.9% | 0.0% | 23.97 |
| bullish EMA stack | 12 | 41.7% | 0.0% | 51.93 |
| Secondary mention — Acquisition | 6 | 0.0% | 0.0% | -0.84 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 185.53 |
| FDA approval | 2 | 0.0% | 0.0% | 5.17 |
| bearish EMA stack | 1 | 0.0% | 0.0% | 7.68 |
| bullish EMA stack; 20-day breakout with relative volume; MACD/RSI bullish moment | 1 | 0.0% | 0.0% | -1.13 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
