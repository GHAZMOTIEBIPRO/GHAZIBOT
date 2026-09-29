# BLACK BOX Ω — Audit, Research, and Repair Report

**Audit date:** 2026-09-29
**Repository:** [GHAZMOTIEBIPRO/GHAZIBOT](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT)
**Repair pull request:** [#117 — `fix: publish live radar status safely`](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/pull/117)
**Prepared status:** reviewed and tested; not merged or deployed to production.

> This system remains **research and non-transactional notification infrastructure only**. No financial transaction, broker action, or order-routing capability was added or used.

## Executive assessment

| Area | Current assessment | Evidence and implication |
|---|---|---|
| Production dashboard availability | **Online, but stale/degraded** | [`/health`](https://ghazibot.vercel.app/health) returned HTTP 200 but carried an August 17 generated timestamp, with production option quote/flow readiness both `false`. [`/data-status`](https://ghazibot.vercel.app/data-status) reported `FALLBACK_ONLY` options. |
| Stock discovery and validation | **Recently working in the observed run** | [Fast discovery run 36584783984](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36584783984) and [stock radar run 36585164299](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36585164299) succeeded. The downloaded stock artifact was generated at 14:46 UTC, had six deep-validated rows, zero errors, and `HEALTHY` stock-path health. |
| Options contract path | **Not production-ready** | A recent [options failure](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36169971081) recorded unconfigured provider credentials, empty Yahoo chain responses, and SEC 403 responses. The dashboard’s public data confirms that the available options path is delayed/unofficial fallback rather than entitled production evidence. |
| Telegram connection | **Historical connectivity evidence, not current delivery proof** | The [connection keeper run](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36311156711) completed identity verification and sealed a destination. No current end-to-end message was sent or claimed during this audit. |
| Public data safety | **Fixed in the repair branch** | The live-status workflow now emits only status metadata, timestamps, count fields, and reason strings. It does not copy contracts, quotes, raw signal rows, credentials, or provider payloads to the public `bot-state` branch. |
| Regression safety | **Green** | Local complete suite: **477 passed**. Both pull-request and push CI checks for PR #117 passed after the final amendment. |

## Confirmed root causes

1. **Dashboard freshness was disconnected from the canonical live paths.** The stock and fast workflows produced fresh short-retention artifacts, but the public web client’s first durable runtime dataset was old. This allowed the dashboard to look online while not accurately describing current path state.
2. **Options data readiness was correctly failing closed, but not sufficiently visible.** The data path did not have an entitled chain provider; therefore it must not issue production-style contract alerts.
3. **Timezone-aware expiration values could trigger a DTE calculation exception.** The current failure evidence included timezone-mixing errors. The repair normalizes provider expirations to timezone-naive UTC calendar dates before calculating DTE.
4. **The failure watchdog did not cover all critical radar paths.** The repair adds the fast discovery, independent stock, classical direction, and standalone thesis paths to the existing failure-watchdog inputs.
5. **A naïve runtime publication approach would have been unsafe.** The audit initially identified that copying full options artifacts to a public branch could conflict with vendor display/redistribution terms. The final repair deliberately publishes metadata only.

## Implemented repair

### 1. Metadata-only live dashboard status

New workflow: `.github/workflows/live-dashboard-status.yml`

After a successful fast-discovery, stock-radar, or options-radar run, the workflow downloads its artifact into the temporary Actions workspace, validates it for secret-like fields, derives only public operational metadata, and commits `live_dashboard_status.json` to `bot-state/runtime/`.

The metadata includes:

- path name and path status;
- artifact generation timestamp and calculated count;
- maximum acceptable age and live freshness state;
- option-provider readiness label and bounded reason strings; and
- the source workflow/run identifier.

It excludes contract rows, quotes, strikes, signal text, raw provider responses, tokens, and credentials.

The dashboard front-end fetches this status independently and displays current path health separately from the older research snapshot. Browser-side age evaluation marks a path stale when its recorded timestamp exceeds the configured safety window.

### 2. Options DTE stability fix

`OptionsRadar._prepare_chain_dates` now parses expiration values as UTC and removes timezone metadata before the DTE subtraction. A regression test covers a timezone-aware expiration input.

### 3. Broader failure notification coverage

The existing Telegram failure watchdog now observes failures/cancellations/timeouts from:

- Fast Explosion Radar;
- Stock Radar;
- Classical Direction Radar; and
- Standalone Intelligence V10,

in addition to the already monitored options, health, and connection workflows.

### 4. Documentation and evidence preservation

The topology document explains the metadata-only boundary. The linked audit-evidence and provider-research documents preserve the observed production facts and cited official-source constraints.

## External data research conclusion

No provider researched supports the combination of **free, real-time, OPRA-quality U.S. option-chain data, and public/multi-user redistribution** under a standard self-service plan.

| Provider | Safe role in this project | Key constraint |
|---|---|---|
| Tradier | Private, account-linked adapter for an entitled individual | Ordinary API use is personal; a public or multi-user application needs partner/licensing review. Sandbox is delayed. |
| Alpaca | Internal delayed/indicative research | Basic options are delayed indicative data, not OPRA; OI was not verified in the reviewed option documentation; redistribution is prohibited. |
| MarketData.app | Delayed or historical internal research with strict credit limits | Free is 24-hour delayed; self-service usage is personal; public display requires commercial/OPRA review. |
| Intrinio | Entitled enterprise/data-vendor path | Realtime is subscription/exchange-entitlement gated; public display needs an order form and appropriate terms. |
| Polygon / Massive | EOD/free research or paid licensed source | Free does not include documented chain snapshots; public display/redistribution needs a commercial license. |

**Operational decision:** keep the options engine in explicit research-only/fail-closed mode until entitlement, timestamp, quote/OI completeness, and display rights are all documented. Do not substitute a free or indicative feed for true production option-flow evidence.

See [provider research](OPTION_DATA_PROVIDER_RESEARCH_2026-09-29.md) for the official-source register and detailed boundaries.

## Validation performed

| Validation | Result |
|---|---|
| Python unit/integration suite | `477 passed` |
| New timezone regression test | Passed |
| New metadata-only publication tests | Passed |
| Real current-artifact metadata validation | Passed; stock metadata showed healthy with count six, while no raw stock artifact was placed in state |
| Ruff for repaired Python modules | Passed |
| Python bytecode compilation | Passed |
| JavaScript syntax (`node --check`) | Passed |
| All GitHub Actions YAML parsing | Passed |
| Git whitespace validation | Passed |
| PR #117 GitHub checks | All four checks passed |

## Remaining production blockers

| Blocker | Why it matters | Required resolution |
|---|---|---|
| Entitled options chain source | Without a lawful real-time/delayed source with documented freshness, bid/ask, OI and relevant terms, options signals must remain research-only | Configure an approved provider account/key and its precise entitlement; do not add any key to chat or repository files. |
| Display/redistribution rights | The dashboard is public; raw vendor options data cannot be copied there under personal/internal terms | Obtain the provider’s written public-display/redistribution permission, or keep provider data private and publish only aggregate metadata. |
| SEC contact user agent | Shared GitHub runner requests received SEC 403s | Configure a descriptive `SEC_USER_AGENT` secret with an operator contact address consistent with SEC fair-access guidance. |
| Current Telegram delivery proof | A connection keeper succeeded previously, but no current message test was performed | After deployment and during an appropriate non-critical test window, use the existing safe connection/status path to verify readiness; do not expose the token or chat ID. |
| Static `/health` endpoint | The Vercel endpoint remains a legacy static health file | The repaired dashboard UI shows dynamic metadata; a later API-backed health endpoint can be added if machine consumers must query fresh status at `/health`. |

## Proposed production activation

Merging PR #117 into `main` will trigger the repository’s existing main-branch Vercel production deployment. Its exact public effect is limited to the reviewed code and documentation above:

- the dashboard will fetch `bot-state/runtime/public/data/live_dashboard_status.json`;
- after successful canonical radar runs, public status metadata will update without publishing raw market/provider payloads; and
- the dashboard will continue to label options as degraded/research-only until the entitlement gate is met.

It will **not** configure provider credentials, change Telegram destination/token, enable a broker, submit orders, or claim that live production options data has become available.
