# GHAZI Radar — Calibration Review

- **Model version:** `2026.08-omega-reengineering`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **197/100**
- **Raw priced signals:** **213**
- **Five-day mature signals:** **176**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 4 | 4 | 1 | 0.0% | 0.0% | 100.0% | 2.12 | -73.15 |
| 70-79 | 83 | 83 | 77 | 22.1% | 9.1% | 67.5% | 21.55 | -79.42 |
| 60-69 | 126 | 126 | 119 | 6.7% | 5.0% | 84.9% | 48.23 | -74.42 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 80 | 10.0% | 78.8% | 55.31 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 52 | 21.2% | 76.9% | 18.28 |
| bearish EMA stack; MACD/RSI bearish momentum | 40 | 0.0% | 90.0% | 21.79 |
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
