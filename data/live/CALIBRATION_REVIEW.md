# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase3`
- **Status:** **COLLECTING MATURE EVIDENCE**
- **Mature signals (1d checkpoint):** **40/100**
- **Raw priced signals:** **133**
- **Five-day mature signals:** **0**
- **Decision:** Collect 60 more signals with a 1d checkpoint before changing weights

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | 0 | — | — | — | — | — |
| 70-79 | 39 | 39 | 8 | 37.5% | 37.5% | 0.0% | 18.27 | -19.36 |
| 60-69 | 94 | 94 | 32 | 59.4% | 46.9% | 3.1% | 24.85 | -19.13 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 26 | 53.8% | 3.8% | 25.62 |
| bearish EMA stack; MACD/RSI bearish momentum | 7 | 57.1% | 0.0% | 22.10 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 4 | 50.0% | 0.0% | 20.48 |
| bullish EMA stack | 3 | 66.7% | 0.0% | 12.91 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
