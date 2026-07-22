# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase2`
- **Status:** **COLLECTING EVIDENCE**
- **Priced signals:** **42/100**
- **Decision:** Collect 58 more priced signals before changing weights

> This report does not authorize automatic score changes. It opens a review gate only. 
> Free-data observations are not proof of executable fills or the order in which targets and stops were reached.

## Score bands

| Band | Signals | Priced | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | — | — | — | — | — |
| 70-79 | 6 | 6 | 0.0% | 0.0% | 0.0% | 1.84 | -4.10 |
| 60-69 | 36 | 36 | 5.6% | 0.0% | 0.0% | 2.91 | -4.10 |
| 0-59 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 30 | 0.0% | 0.0% | 2.48 |
| bullish EMA stack | 7 | 28.6% | 0.0% | 6.01 |
| FDA approval record — verify materiality | 2 | 0.0% | 0.0% | 0.35 |
| FDA approval | 2 | 0.0% | 0.0% | -0.65 |
| bearish EMA stack; MACD/RSI bearish momentum | 1 | 0.0% | 0.0% | -0.33 |

## Review protocol

When the gate becomes ready:

1. Freeze the current model version and preserve its complete signal journal.
2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.
3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.
4. Reject weight changes that improve only the same sample used to propose them.
5. Create a new model version and test it prospectively; never overwrite historical scores.
6. Do not enable real-money automation solely because the minimum sample was reached.

_Generated from `data/live/calibration.json`._
