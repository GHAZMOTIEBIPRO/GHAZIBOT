# GHAZI RADAR PRO — Commercial Research Platform Execution Plan

**Date:** 2026-11-12 | **Status:** PRODUCT SPECIFICATION ONLY — not implemented, tested, deployed or licensed.  
**Working branch:** `feat/ghazi-radar-commercial-platform-20261112`. Keep `main` and existing production paths untouched until review.

## 1. Mission and actual starting point

Turn the existing Arabic mobile-first US markets research dashboard and Telegram companion into a **sellable research software product**. Preserve the three independent engines specified in `AGENTS.md`: Explosion Stocks, Classical Direction (underlying-first CALL/PUT/WAIT), and Option Explosion. No order placement or claims of trade-ready execution.

Existing assets observed on `main`: `public/index.html`, radar/chart/terminal JS assets, `options_radar/`, `tests/`, GitHub workflows, a static `public/` Vercel site, public research artifacts, and documentation. This is not a greenfield reimplementation.

**Evidence baseline:** `docs/GHAZI_RADAR_ACCURACY_AUDIT_2026-10-31.md` reported **NOT TRADE READY**. This is an October 31 snapshot, not a fresh November 12 validation. No live-production access was confirmed as part of this specification.

## 2. Product boundaries

**Sell:** workflow, research views, watchlist management, historical analytics, reproducible reports, user-specific saved screens, filters, cross-source research summaries, event timelines, and alerts **only where distribution rights permit**.

**Do not imply:** guaranteed profit, options-fill quality, live consolidated US market data, real dealer GEX, actual institutional flow, licensed investment advice, or trader-verified options P&L unless each requirement is independently substantiated.

Research categories:
1. Market overview: SPX/NDX/SPY/QQQ and major-cap equities with as-of times, differing instruments clearly separated.
2. Symbol workbench: timeframes, levels, scenarios, invalidation, catalysts, provenance, stale/missing flags.
3. Catalyst radar: SEC/FDA/official issuer sources and dated material-event chronology, with attribution, impact **hypothesis** not proven reaction.
4. Options lab: educational contract screeners, DTE, spread, liquidity, volatility, Greeks and scenario risk only when licensed evidence exists. Show NOT AVAILABLE rather than estimate unavailable live fields.
5. Strategy evidence lab: cohort selection, event-time backtesting, out-of-sample windows, costs, same-bar ambiguity, source-grade and denominators.
6. Private workspaces: users save watchlists, alert rules and reports; independent Telegram opt-in when a permitted source path supports delivery.
7. Publisher/admin: operational readiness, provider freshness, licensing matrix, user billing, billing webhooks, audit events and exportable usage metrics.

**MVP requires features 1, 2, 3, 5 and private workspaces.** Options lab remains a clearly marked research-beta path until feed entitlements are cleared.

## 3. Commercial and data compliance gates (P0, fail closed)

* Read the active terms and contracts for **every** upstream feed. Inspect `docs/DATA_RIGHTS_MATRIX_2026-10-21.md`, `data/source_rights.json`, `options_radar/source_permissions.py`, `scripts/price_source_gate.py`, `options_radar/public_guard.py`.
* Distinguish owner-private analysis from public paid-user display, cache, redistribution, Telegram distribution and derived signals. Free individual APIs do not confer resale rights.
* Avoid republishing Alpaca personal-user prices or other individually licensed provider data to paid customers. Explicit written approval/vendor commercial package is required where terms restrict this.
* Evaluate CMA advising/securities business categorization in Saudi Arabia before offering actionable tailored recommendations. Product v1 must be informational **research software**, not execution or advice marketed as guaranteed.
* Validate hosting commercial eligibility before monetization; Vercel Hobby is non-commercial-only according to Vercel terms. Confirm provider tier and budget.
* Never require Claude Pro/Claude Code for runtime. No model inference may be essential for basic operation. If premium text summarization is later offered, require independent paid API billing, guardrails and cost caps.
* Keep secrets out of git/public exports. `main` must not be altered by new experiment branches until PR approval.

## 4. Recommended architecture (reuse before replacing)

Maintain existing Python collectors/independent engines and GitHub state writers. Add a **new product-serving layer** (architecture selection gated on repo inspection) with:
- Python APIs using a small FastAPI service **or** equivalent adapter that reuses validated published outputs; keep existing stable static pages intact.
- Database: PostgreSQL with explicit per-user row-level isolation. Do not use machine-managed `bot-state` as a shared writable SaaS user database.
- Authentication: verified email, session expiry, password reset or passwordless, rate limiting, anti-enumeration and device session revocation.
- Authorization: server-side entitlements, roles `anonymous/free/pro/admin`, strict read/write boundaries. Never rely on client-only paywall checks.
- Billing abstraction: Saudi-supported processor chosen **after** vetting API, subscriptions, refunds, webhooks, Saudi compliance and fees. Implement signed, idempotent webhook handler, grace periods, failed renewal, cancellation and refunds.
- Frontend: reuse existing Arabic mobile-first UI and static research output; introduce account and saved workspace panels incrementally.
- Background tasks: existing orchestrator owns market data; account/report/billing jobs separate, with deduplicated delivery and queue limits.
- Logs/metrics: redact PII/tokens, track job freshness, API reliability and subscription events; backup + restore tests.

**Proposed DB entities:** users, sessions, workspaces, watchlists, watchlist_symbols, saved_screens, alert_rules, notification_destinations, reports, plans, subscriptions, invoices, billing_events, audit_events, provider_rights, dataset_snapshots, analysis_events, signal_evaluations.

## 5. Initial packaging / price experiment (not a sales claim)

| Tier | Hypothesis price | Included | Excluded until licensed |
|------|------------------|----------|-------------------------|
| Free | SAR 0 | public explainers, dated market overview, limited watchlist, delayed/official-content research views where allowed | live premium data, tailored advice |
| Research Plus | SAR 49–99 / month | private watchlists, saved research views, custom filters, official events, exportable reports, supported alerts | quote redistribution without rights |
| Research Pro | SAR 149–249 / month | expanded saved strategies, outcome-lab access, backtest controls, report bundles and prioritized product support | guaranteed signals, auto-trading |

All prices are experiments to test with customers, not established market facts. First milestone: **five design-partner interviews and three paid pilots** for legally serviceable research features. No subscriber/revenue claims without actual records.

## 6. Engineering work packages and acceptance criteria

### P0 — Reality audit and production safety
- Map all existing UI routes/modules, workflows and single-writer state ownership.
- Run current tests (pytest, Ruff, compileall, Node checks, UI/browser acceptance where available).
- Inventory real provider entitlements, source/quote timestamps, data freshness, live deployed build SHA, and missing capabilities.
- Produce `docs/PLATFORM_P0_BASELINE.md` with CODED/TESTED/CI GREEN/RUNTIME VERIFIED/EMPIRICALLY VALIDATED separation.
- No use of "trade ready" absent execution and OOS evidence.

**Accept when:** reproducible matrix of capabilities × source × commercial rights × quote freshness × status exists, with traceable raw evidence. Existing production still works.

### P1 — Commercial alpha behind a feature flag
- Build responsive Arabic account dashboard and authenticated saved watchlists without refactoring existing radars.
- Persist users and watchlists in a DB with ownership checks on every read/write.
- Add account data export and deletion, basic consent/privacy notice and internal audit logs.
- Provide anonymous/public fallback so current site does not break.
- Feature-flag the alpha in a separate preview environment.

**Accept when:** 2 simulated users cannot access each other's data (negative server tests); smoke tests pass mobile and desktop; no public data leak.

### P2 — Research product differentiation
- Per-ticker research workspace showing source, timestamps, daily/intraday conditional on licenses, event timeline, context levels, uncertainty, and linked official filings.
- Prospective paper research ledger with frozen timestamped candidates and post-event evaluations.
- Time-split OOS lab, slippage sensitivity, same-bar ambiguity, market regime breakdown, sample sufficiency; report denominators and uncertainties.

**Accept when:** deliberately stale/missing/licensing-blocked fixtures never produce fresh-price claims or premium option trade alerts.

### P3 — Payments/launch only after contracts
- Validate legal permissions, commercial hosting plan and payment provider support.
- Implement server-side plan entitlement checks; signed + idempotent webhooks.
- Test canceled/refunded/expired grace and duplicate callback flows.
- Add transparent billing and support pages.

**Accept when:** sandbox billing passes every edge-case test and first signed design-partner agreements can be served without illegal data redistribution.

## 7. Verification checklist

- Original `AGENTS.md`, `CLAUDE.md`, V11 gates, site publishers and workflow cadence must remain unchanged unless justified by tests.
- Security: session fixation, IDOR, CSRF, XSS, webhook replay, rate limits, dangerous downloads and injection. No private tokens in client JS or GitHub CI logs.
- Product: mobile RTL, keyboard accessibility, 44px tap targets, pricing limitations visible next to the service.
- Data: origin, license, actual quote timestamp, publish-time vs generated-at, corporate actions, independent sources.
- Analytics: forward-only data, survivorship/look-ahead bias checks, fees/spread/slippage assumptions, reproducible records.
- CI: gate on current repository tests plus new auth/entitlement tests and browser acceptance.
- Shipping: reviewer-approved PR, preview, CI green, explicit promotion, production probe and rollback.

## 8. Claude Code execution instruction

```
You are the lead engineer for GHAZI RADAR PRO. Read AGENTS.md and CLAUDE.md.
Open docs/GHAZI_RADAR_COMMERCIAL_PLATFORM_2026-11-12.md. First compare its
assumptions with latest origin/main and open PRs. Perform P0 audit with
evidence, not promises. Then implement only P1 under a new feature flag and
separate branch, with tests. Never bypass provider licensing, V11, OOS gates,
or privacy controls. Preserve current site and bot. Open a draft PR containing
test results, screenshots if actually captured, a data-rights impact assessment,
and remaining blockers. Do not merge, deploy or incur paid services without
explicit owner approval. Start execution instead of rewriting the plan.
```

## 9. Required owner decisions before *live* commercial launch

1. Legal/regulated-service review for contemplated research features and messages.
2. Written commercial display/redistribution agreements or a licensed-data-free launch scope.
3. Payment processor and merchant entity; production data retention/privacy policy.
4. Hosting tier and spend ceilings; confirmation of which Vercel team/project owns production.
5. Pilot users and pricing evidence.

## 10. Known limitations at time of this document

- Vercel authenticated inspection could not identify project in the current connected scope; no live deployment was verified.
- No current commercial market-data entitlements or live option quote quality were verified.
- No unit tests or CI were executed by this documentation-only change.
- The October accuracy audit is historical and must be refreshed before product claims.
