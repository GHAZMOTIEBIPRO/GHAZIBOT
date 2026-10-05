# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **194/100**
- **Raw priced signals:** **208**
- **Five-day mature signals:** **175**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 2 | 2 | 1 | 0.0% | 0.0% | 100.0% | 2.12 | -73.15 |
| 70-79 | 81 | 81 | 75 | 22.7% | 9.3% | 69.3% | 20.59 | -80.75 |
| 60-69 | 125 | 125 | 118 | 6.8% | 5.1% | 85.6% | 48.61 | -74.44 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 78 | 10.3% | 80.8% | 55.25 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 52 | 21.2% | 76.9% | 18.28 |
| bearish EMA stack; MACD/RSI bearish momentum | 39 | 0.0% | 92.3% | 22.27 |
| bullish EMA stack | 13 | 0.0% | 84.6% | 51.29 |
| Secondary mention — Acquisition | 6 | 100.0% | 0.0% | -0.84 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 185.53 |
| FDA approval | 2 | 0.0% | 100.0% | 57.30 |
| bearish EMA stack | 1 | 0.0% | 100.0% | 7.68 |
| bullish EMA stack; 20-day breakout with relative volume; MACD/RSI bullish moment | 1 | 0.0% | 100.0% | -1.13 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
