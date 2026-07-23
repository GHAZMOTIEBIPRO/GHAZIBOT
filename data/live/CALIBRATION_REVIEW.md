# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase2`
- **Status:** **COLLECTING MATURE EVIDENCE**
- **Mature signals (1d checkpoint):** **19/100**
- **Raw priced signals:** **87**
- **Five-day mature signals:** **0**
- **Decision:** Collect 81 more signals with a 1d checkpoint before changing weights

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | 0 | — | — | — | — | — |
| 70-79 | 31 | 31 | 4 | 0.0% | 0.0% | 0.0% | 4.19 | -27.66 |
| 60-69 | 56 | 56 | 15 | 13.3% | 0.0% | 0.0% | 7.24 | -19.75 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 14 | 0.0% | 0.0% | 4.75 |
| bearish EMA stack; MACD/RSI bearish momentum | 3 | 0.0% | 0.0% | 8.94 |
| bullish EMA stack | 2 | 100.0% | 0.0% | 16.06 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
