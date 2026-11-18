# Quant research roadmap (2026-11-17)

Principle: most requested engines already exist in some form. The binding constraint is **lawful data plus valid
measurement**, not code. Order of work follows the directive: P0 data reliability and licensing, P1 signal
evaluation, P2 Fibonacci / reversal / breakout, P3 options validation, P4 dashboard, P5 AI experiments. No engine
may claim predictive superiority without out-of-sample evidence (AGENTS.md).

## Engines A–L mapped to the repository

| Engine | Existing code | Data it needs | State | Next step |
|---|---|---|---|---|
| A Fibonacci Master | `opening_fib_scan.py`, `opening_fib_context.py`, `opening_fib_replay.py`, `scripts/run_opening_fib_daily.py`, `run_opening_fib_shadow.py` | Alpaca SIP bars (owner-private) | RUNTIME VERIFIED: private delivery and shadow on 2026-11-17 | Multi-timeframe confluence stays private; publish nothing derived (Alpaca `publish_derived` UNVERIFIED) |
| B Liquidity Map | `liquidity_monitor.py` (funding), `volume_liquidity.py`, `structure_liquidity_shadow.py` | Intraday bars for price liquidity; funding data is public | Funding: IN USE. Price liquidity: shadow | Previous high / low, opening range, VWAP in the private Fib job only |
| C Reversal Radar | No dedicated module; classical CALL / PUT / WAIT (`classical-direction-radar.yml`) | Bars | Gap | Define confirmed reversal events; evaluate with the v2 outcome evaluator before any alert |
| D Breakout Hunter | `breakout_pressure.py`, `daily_volume_breakout_shadow.py`, `vcp_minervini_shadow.py`, explosion radar | Bars and volume | Shadow; public radar degraded (no lawful bars) | Same evaluation path as C |
| E Institutional Intelligence | None (`institutional_radar.py` is an explosion-stage classifier) | SEC 13F, Form 3/4/5 data sets | Gap; SEC answers 403 | Needs `SEC_USER_AGENT`; then archive increment 1 (`data-architecture.md`); label delayed disclosures |
| F Options Intelligence | `v11_gate.py`, `data_fabric.py`, `free_gamma_engine.py`, `free_gex_validation.py`, `gamma_interpretation.py` | Licensed, two-sided, timestamped chains | Blocked by licence (Cboe / OCC terms; no Tradier entitlement) | V11 unchanged; py_vollib only with licensed chains |
| G Catalyst Radar | `catalysts.py`, `official_catalyst_intelligence.py`, `strict_catalysts.py`, `catalyst_impact.py` | openFDA, ClinicalTrials, GDELT, SEC | IN USE (SEC part blocked) | SEC filings once access works |
| H Market Regime | `market_regime.py`, `macro_regimes.py` | Index bars and macro | Macro part works; price part data-gated | Use the public macro archive (increment 2) for regime history |
| I Target Projection | `omega_target_map.py`, `target_horizon.py`, `premium_target_engine.py`, `omega_target_learning.py` | Bars | **Evaluation v2 fixed in PR #440**; no valid cohort yet | Owner-private re-measurement of the 414 legacy signals; then alternative target definitions out of sample |
| J Signal Quality | `trust_verdict.py`, `phase62_quality.py`, `audit_quality.py` | Matured outcomes | Exists | alphalens-reloaded IC analysis once v2 outcomes exist |
| K Outcome Tracker | `outcomes.py`, `stock_outcomes.py`, `stock_outcome_archive.py`, signal ledger (`SIGNAL_LEDGER_AR.md`) | Bars | Exists; MFE / MAE recorded in the stock audit | Ensure every tracker uses session-complete maturity (the v2 rule) |
| L Data Trust | `free_data_health`, `source_agreement`, `provider_readiness.py`, `ohlcv_quality.py`, `output_policy.py` | — | Exists | Reconcile the Treasury health conflict (registry) |

## Mission 5 plan (412 signals): next phases

1. **Done (PR #440).**
   - Exact reproduction of the baseline.
   - The premature-maturity defect is fixed.
   - The legacy baseline is preserved as invalid evidence (`signal-validation-report.md`).
2. **Owner-private re-measurement** of the 414 legacy signals on Alpaca SIP bars under rule v2. It reports:
   - n, hits, stops, ambiguous and misses;
   - the Wilson 95 % CI;
   - a breakdown by session phase (regular / pre-market / after close).

   Delivery is by Telegram only, never logs.
3. **Alternative target hypotheses**, each fixed before looking at outcomes:
   - H1: T1 = 1 × ATR(14, daily) with a 1-session horizon;
   - H2: T1 = prior session high / low;
   - H3: activation only after a break of the opening range.

   They are compared on signals from sessions **after** the definition date (out of sample by time). The sample
   sizes and CIs are reported; promotion requires the existing sample gates (100 global, 30 per cohort).
4. **No live alert or public metric changes** until step 3 passes the gates.

## Owner decisions that unblock the most

| Decision | Unblocks |
|---|---|
| Set `SEC_USER_AGENT` | Engines E and G (SEC part), archive increment 1 |
| Choose a price licence with derived-display rights, or accept private-only price analytics | Public A / B / C / D / H / I output |
| Options licence (vendor agreement) or keep options research-only | Engine F |
| `TELEGRAM_OWNER_USERNAME` | Binds private delivery to the owner's username as well as chat type |
