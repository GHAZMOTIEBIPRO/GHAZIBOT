# GHAZI Radar — Calibration Review

- **Model version:** `2026.07-phase2`
- **Status:** **COLLECTING EVIDENCE**
- **Priced signals:** **39/100**
- **Decision:** Collect 61 more priced signals before changing weights

> This report does not authorize automatic score changes. It opens a review gate only. 
> Free-data observations are not proof of executable fills or the order in which targets and stops were reached.

## Score bands

| Band | Signals | Priced | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 90-100 | 0 | 0 | — | — | — | — | — |
| 80-89 | 0 | 0 | — | — | — | — | — |
| 70-79 | 5 | 5 | 0.0% | 0.0% | 0.0% | 1.35 | -3.83 |
| 60-69 | 34 | 34 | 0.0% | 0.0% | 0.0% | 1.23 | -3.14 |
| 0-59 | 0 | 0 | — | — | — | — | — |

## Catalyst groups

| Catalyst | Signals | Target 1 | Stop | Avg MFE % |
|---|---:|---:|---:|---:|
| bullish EMA stack; MACD/RSI bullish momentum | 27 | 0.0% | 0.0% | 0.78 |
| bullish EMA stack | 7 | 0.0% | 0.0% | 4.04 |
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
