# GHAZI RADAR — Real trading-readiness verdict, 2026-10-22

**Goal:** a source-backed no-trading verdict and auditable measurements, not more speculative indicators or a fabricated profitability claim.

## Ownership and data flow

Reuse the single existing `.github/workflows/site-evidence-strength.yml` publisher, which already schedules evidence checks and updates `bot-state`. New `scripts/build_trading_readiness.py` reads *only already-published files* from the checked-out `bot-state`, without making any market-data HTTP calls, installing dependencies, sending Telegram messages or changing trading logic.

Inputs:
- `runtime/public/data/production_access_health.json`: external HTTP and Telegram Bot API access checks (not a delivered trading alert).
- `runtime/public/data/data-status.json`: source operational flags, quote-flow readiness, freshness. This is not a live quote timestamp.
- `runtime/public/data/stock_watch_charts.json`: actual completed chart objects and copyright/source restrictions.
- `runtime/public/data/source_agreement.json`: independently authorized source comparison.
- `runtime/public/data/stock_audit_public.json`: audited historical outcomes and independent close-time-integrity counts.
- `state/stocks/stock_walk_forward.json`: independent time-split out-of-sample gate.
- `runtime/data/live/omega_target_calibration.json`: per-target/horizon historical samples.
- `state/performance/options_performance_report.json`: qualified contract exit/entry outcome samples and calibration.
- `runtime/public/data/explosion_stage_evaluation.json`: *modelled*, not executed, cost-adjusted expectancy.
- `runtime/public/data/site_strength.json`: source-evidence score, not a win rate.

Output is `runtime/public/data/trading_readiness.json`, version `ghazi.trading_readiness.v1`. Public Arabic read-only page `/trading-readiness.html` fetches the source report and refuses stale (>36h), malformed, and prematurely marked ready reports. The main terminal nav links directly to the page.

## Initial facts requiring independent follow-up

At review time:
- The website domains passed an external HTTP access check, but site accessibility **does not equal market-data availability**.
- Price chart feed was `SOURCE_TERMS_BLOCKED`, `symbols={}`; source agreement `NOT_VERIFIED`, and option source had no verified execution quotes.
- The public stock audit counted **714 audit records, 58 newer individually close-verified records**, `proven_edge=false`.
- Stock walk-forward recorded `research_passed=false` and `live_promotion_allowed=false`.
- Target calibration had **412 matured intraday T1 records, 8 historical T1 hits = 1.94%**. Its `calibration_ready=true` refers to sample gates **not a tradable edge or forecast certainty**. T2/T3 did not hit within their corresponding intraday cohort at that observation.
- Options performance had **0 eligible closed samples** and inactive calibration.
- Stage performance: published modelled net expectancy of **-1.252%** pressure building, **-2.385%** ignition, **-1.422%** explosion, with costs **assumed**, *not measured real fills*.
- An existing research-only source-evidence-strength score of 14/100, not a trade win rate.

The report refuses any inferred win probability, profitability or investment-grade trade signal, and its two action flags remain **false** even if all future reported research checks become true: `trade_recommendations_authorized=false`, `automated_execution_allowed=false`. The existing strict V11 per-contract execution gate is untouched.

## Follow-up requirements before reassessment

Collect market feed permissions and legitimately independent, provider-time-stamped source observations; preserve stale/source-rights fail-closed behavior; prospectively demonstrate walk-forward edge, separated by time, cohorts and quote/source family; collect 100+ properly structured executed-grade options research observations with entry/exit bid/ask and spread/cost inputs. Audit material drift and outages. **Do not activate live orders automatically**.

## Delivery contract

Each iteration: full CI, merge only when green, verify new bot-state readiness JSON and Vercel site deployment; report operational reality rather than declaring 100% trading reliability.
