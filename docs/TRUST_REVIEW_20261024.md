# Trust review — 2026-10-24

## Evidence and implemented fixes

| Finding | Correction | Remaining limit |
|---|---|---|
| QuantStats accepted historical rows without completed-bar measurement v2 | Exclude legacy/unreverified decisive rows and report exclusion count; reapply sample/session minimums | A valid schema or old success label is not evidence of predictive edge |
| Public reliability digest trusted a statistics status without binding inputs | Require canonical audit SHA-256, explicit research authority and v2 requirement | Hash is provenance consistency, not proof of provider accuracy |
| SEC EFTS probe claimed alternative feeds were active without observing them | Separate configured alternatives from verified-active alternatives; remove unsupported 403 claim | No bypass of SEC access restrictions |
| Live-status publisher silently skipped runs with no scan artifact | Publish an unavailable attempt with missing-artifact reason and retain last data timestamp | Does not infer whether the cause was market closure, permission gating or another condition |
| Publisher inferred options flow readiness from quote readiness | Carry two independent explicit flags, expire readiness for stale/critical payloads | Contract-level V11 checks are still required |
| Future and naive timestamps could appear current; UI retained historical readiness | Reject invalid/future timestamps; require fresh runtime report before displaying readiness | Public report freshness is not a live quote timestamp |

## Runtime ownership
No added timer or independent market-data writer. `stock-outcome-auditor.yml` retains
ownership of audit and reliability summaries. `live-dashboard-status.yml` retains
ownership of path status. Missing-artifact runs update only live dashboard status,
not the market-health timestamps or prior source observations. SEC changes amend
its existing probe status only. No Telegram messages are added by this change.

## Data-source review
Existing yfinance/yahooquery transports remain one Yahoo family. EdgarTools is an
adapter, not an independent source or an access-rights grant. FederalRegister.gov's
public API is a possible future regulatory-context feed, but is not an SEC filing
replacement or price/option feed. It is intentionally not added to repair unrelated
measurement defects. No external project code was copied for these corrections.

## Acceptance
Run real existing CI, regression cases for all findings, deploy and inspect runtime
outputs. The previous 724 structurally valid records and 347 eligible observations
must not be reported as a validated trading track record. Recompute eligibility
using completed-bar version 2; preserve unresolved/legacy records for audit rather
than converting or deleting them. Out-of-sample edge, execution costs and licensed
option data remain separate unfulfilled requirements.
