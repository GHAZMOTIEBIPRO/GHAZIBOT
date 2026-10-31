# GHAZI RADAR — Independent accuracy and trust audit
**As of 31 Oct 2026 (Riyadh). Evidence snapshot: bot-state produced 2026-10-30T22:50 UTC; reviewed source code and GitHub Actions.**

## Verdict
**NOT TRADE READY.** GitHub workflow success demonstrates that a command completed, not that market-data entitlements, live quote timestamps, future price direction or profitable options fills are verified.

### Reconciled production evidence
| Control / metric | Measured state | Interpretation |
|---|---:|---|
| stock candidate rows | 0 | no current verified stock setups from this report |
| option candidate rows | 0 | no current executable option candidates |
| independent non-Yahoo stock families | 0 | no verified licensed independent price crosscheck |
| current option execution quotes and true flow | both false | CALL/PUT execution veto remains |
| latest index radar | SOURCE_TERMS_BLOCKED | no SPX/NDX authenticated live index read |
| SEC issuer filings | HTTP 403, zero verified issuers | SEC catalysts incomplete; available company-IR releases are a separate source |
| CFTC ES/NQ | reports through 2026-10-20 | weekly index **futures** positioning, not intraday option dealer gamma |
| Treasury curve | through 2026-10-29 | macro context, not option execution |
| official company IR | 10 feeds and 21 items at prior verified snapshot | headlines/dates/links, with topic not issuer-price impact proven |
| historical signal records | 247 tracked, 128 path evaluated | not 247 actual fills |
| target-first / stop-first / ambiguous | 28 / 84 / 0 | 21.875% target-first and 65.625% stop-first among 128; **16 unclassified** in that denominator |
| path result basis | 0 contract / 128 underlying-proxy | the entire evaluated path cohort is **not option P&L** |
| research calibration | 230 mature checkpoints, sample gate true | minimum sample count, **not** an edge, probability or fill-quality result |
| trading-readiness published verdict | NOT_TRADE_READY | six blocking conditions, including independent market prices, execution OPRA, out-of-sample validation |

**Important comparability note:** the historical 28/84/128 cohort is a **historical, modeled-path** cohort. It is not the same population or clock as the 0 current contract candidates. It is invalid to compute realized profitability from it; fill prices, spreads, transaction costs and marketable quote history are missing. The 247 calibration records and 128 path-evaluated records use different eligibility filters and denominators.

### Source and software audit: confirmed weaknesses
1. **P1 false active-data reporting (fixed).** `phase6_publisher.build_source_network` previously marked Yahoo stocks/options active solely because an empty `stocks` or `options` list existed. `active_option_sources=1` could be rendered when `option_chain_source_families=[]` and `options_execution_quote_ready=false`. Active now requires actual provider success plus source permission; the public-quality widget uses verified families, not a generic count.
2. **P1 heterogeneous evidence promoted as trade entry (fixed).** Public `_stock_recommendation` counted Yahoo as a price source plus an official news catalyst and inferred `دخول مشروط`; `_contract_recommendation` could count option history and a headline as independent execution confirmations. The generic public reporter is now **research-watch only** and marks confidence as a heuristic priority, not an empirical win probability. Separate, properly licensed, per-contract execution gates are unaffected.
3. **P1 calibration wording (fixed).** A ready minimum-sample gate previously looked like model readiness. Visible classic UI now explicitly says the sample is not proof of option profitability and exposes counts for actual option-contract vs underlying-proxy paths.
4. **P1 absent readiness object broke health panel (fixed).** Public runtime `data-status.json` legitimately reports `option_provider_readiness=null`; `ghazi-radar-quality.js` formerly rejected the entire JSON document even when `coverage_diagnostics` correctly showed blocked quotes/flow. It now accepts the valid document and shows unavailable execution evidence.
5. **P1 no explicit cross-file truth summary (fixed).** A new stdlib-only `trust_verdict.py` independently checks timestamps, source entitlement proxies, current quote/flow flags, critical errors, and outcome-counter consistency. The runtime state vault stamps this verdict in both public `latest.json` and `data-status.json` *after* price/rights redaction. No extra market-data requests, no execution signals or raw quotes.

### Remaining P0 blockers, not fixed by adding open-source software
- No non-Yahoo licensed independent real-time price family presently configured on the GitHub production runner; Alpaca, Twelve Data and Tradier source checks reported missing keys and/or unrecorded owner terms authorization.
- Cboe's official consolidated OPRA options trades/quotes and timely 0DTE dealer-position inference are **not** produced by the free indicative Alpaca feed or by CFTC weekly futures positioning. Real dealer GEX cannot be observed from OI alone.
- SEC official submissions/EFTS on shared GitHub runners remain HTTP 403 or cooled down. A legitimate operator/contact `SEC_USER_AGENT` and official access-resilience fixes are needed; do not evade the denial or call stale mirror data current.
- Out-of-sample, time-split, fee/spread-adjusted performance **not proven**. Previous published stock walk-forward reported failure and option premium closes were zero; must obtain authorized historical execution-grade evidence before re-evaluation.
- Actual broker-side Telegram order execution, delivery latency, and marketable bid/ask slippage have **not** been proven by unit-test success or an operational bot-status message.
- A research-grade GEX proxy cannot certify dealer book, net aggressor flow, buy-to-open or full SPX 0DTE flow. The provenance and expiry coverage must be labeled in every associated result.

### Trust acceptance gates, ordered
1. Verify authorized independent stock quote time, NY session and effective rights for *each account/symbol*. Stock crosscheck: two distinct providers within a fixed time tolerance. Do not treat multiple libraries wrapping one feed as independent.
2. For every **option contract** require exact OCC identity (SPX/SPXW vs SPY, NDX/NDXP vs QQQ), expiry/type, source/exchange rights, fresh two-sided executable bid/ask, spread/volume/OI with timestamps, and no adjusted contract ambiguity.
3. Actual OHLC from option contracts or documented marketable bid/ask fills; never substitute the underlying return for option P&L. Reserve a clean holdout period; freeze decisions before collecting outcomes.
4. Count eligible attempted trades, fills, stale rejects, skipped symbols, matched source timestamps, exit causes, costs and slippage. Publish precision/recall/calibration only on sufficiently sized, independent out-of-sample observations, with confidence intervals and the cohort denominator.
5. Continue fail-closed V11 guard and human review. No model or heuristic permits execution if any source permission, timing or price-grade gate fails.

## Reproducibility and sources
- GitHub `bot-state/runtime/public/data/latest.json`, `data-status.json`, `index_radar.json`, `sec_filing_pulse.json`, `public_macro.json`, `ir_news.json`, `trading_readiness.json`.
- `options_radar/outcomes.py`, `calibration.py`, `phase6_publisher.py`, `phase60_source_network.py`, `public/ghazi-radar-quality.js`, `scripts/runtime_state_vault.py`.
- Vendor authority: Cboe OPRA interval and trade data https://datashop.cboe.com/option-quote-intervals ; https://datashop.cboe.com/option-trades .
- Public OI position-sign limitations: https://spotgamma.com/gamma-exposure-gex/ ; https://spotgamma.com/what-is-gex-gamma-exposure/ .
- US SEC fair-access and financial data: https://www.sec.gov/about/developer-resources .
- CI regression: `tests/test_trust_verdict.py`, plus the pre-existing full suite and browser smoke.

**No claimed 100% accuracy and no guaranteed positive returns.**
