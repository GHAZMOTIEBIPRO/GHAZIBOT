# QuantStats non-annualized signal-outcome validation

QuantStats ([Apache-2.0](https://github.com/ranaroussi/quantstats)) is an **optional** open-source statistical reference library in `requirements-research.txt`. The existing Stock Outcome Auditor remains the sole owner of its `stock_outcome_audit.json` durable state and 5-minute source-freshness policies. This adapter only **reads** the matured audit and writes a distinct `quantstats_stock_signals_shadow.json` research artifact during the same workflow run.

It uses `options_radar.stock_walk_forward._eligible_decisive_rows` to exclude invalid sessions, ambiguous same-bar outcomes, unavailable/non-decisive records, unqualified 60m checkpoints and missing scores. No statistics are published unless there are >=20 eligible events across >=10 independent sessions with audit 60m coverage >=90%.

It calls QuantStats `stats.win_rate` and `stats.profit_factor` on *non-annualized, equally weighted, signed directional returns over each signal's 60-minute window*. It **does not** compute or claim annualized Sharpe, CAGR, drawdown, real broker fills, options returns, portfolio results, or probabilities of future profit. Events overlap; the sample is not a daily NAV or an executable performance record.

If data are insufficient, or QuantStats is unavailable, the output is `INSUFFICIENT_EVIDENCE` or `UNAVAILABLE`, respectively. These results are not allowed to change stock scores or option V11 gates. The existing research validator installs QuantStats and runs an actual runtime smoke.

```bash
python -m scripts.run_quantstats_stock_shadow --audit data/live/stock_outcome_audit.json --output data/live/quantstats_stock_signals_shadow.json
pytest -q tests/test_quantstats_stock_shadow.py
```

Inspect the `stock-outcome-audit-state` artifact for `quantstats_stock_signals_shadow.json` along with the original outcome audit. This does not require a paid feed or a new scheduler. Source correctness is only as reliable as the underlying Yahoo research observations and auditing policy.
