# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase6.2-evidence-tiers`
- **Status:** **READY FOR INDEPENDENT REVIEW**
- **Mature signals (1d checkpoint):** **179/100**
- **Raw priced signals:** **187**
- **Five-day mature signals:** **57**
- **Decision:** Eligible for independent score recalibration review

> Same-scan observations do not count toward calibration readiness. 
> This report does not authorize automatic score changes. Free-data observations are not proof of executable fills or target/stop ordering.

## Score bands

| Band | Signals | Observed | Mature | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | 0 | — | — | — | — | — |
| 70-79 | 70 | 70 | 67 | 6.0% | 6.0% | 0.0% | 8.73 | -34.18 |
| 60-69 | 117 | 117 | 112 | 25.9% | 18.8% | 0.9% | 23.35 | -32.00 |
| 0-59 | 0 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Mature signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 71 | 28.2% | 1.4% | 26.14 |
| bearish EMA stack; 20-day breakdown with relative volume; MACD/RSI bearish momen | 50 | 6.0% | 0.0% | 9.28 |
| bearish EMA stack; MACD/RSI bearish momentum | 35 | 14.3% | 0.0% | 13.31 |
| bullish EMA stack | 12 | 41.7% | 0.0% | 13.49 |
| Secondary mention — Acquisition | 6 | 0.0% | 0.0% | -0.84 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 125.68 |
| FDA approval | 2 | 0.0% | 0.0% | -0.65 |
| bearish EMA stack | 1 | 0.0% | 0.0% | 7.68 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
