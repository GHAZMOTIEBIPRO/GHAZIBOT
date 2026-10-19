# Free Data Source Policy

The radar uses only sources whose public documentation permits programmatic access.

## Enabled without private credentials

- SEC EDGAR submissions, filing documents and XBRL Company Facts APIs, with a descriptive User-Agent and fair-access throttling.
- openFDA public API.
- ClinicalTrials.gov API v2 for recent industry study-registry updates and newly posted registry results. Registry data is sponsor-submitted; it can prove that a registry record changed or results were posted, but it cannot by itself prove a positive/negative clinical outcome.
- Nasdaq public market-movers response as best-effort universe discovery.
- Yahoo/yfinance as an unofficial research fallback, explicitly labelled as such.
- U.S. Treasury public daily yield-curve XML feed for slow-moving macro context.
- U.S. Bureau of Labor Statistics unregistered public API v1: official monthly CPI, unemployment and payroll context via one daily batch (not prices, option-flow evidence, or signals). BLS limits unregistered use to 25 calls/day and requires source/retrieval-date attribution.

## Optional free-account integrations

- Tradier developer/brokerage API.
- Alpaca market-data API.
- Twelve Data Basic API.
- Polygon Stocks Basic API.
- Alpha Vantage standard API.
- FRED API.

Each optional source is disabled until its own API key is present in GitHub Secrets. The radar never publishes a secret.

## Intentionally excluded

- Automated extraction of Cboe delayed quote tables. Cboe's delayed-quotes pages expressly prohibit automated extraction/download, so the project does not call undocumented quote-table endpoints.
- Finnhub stock candles and bid/ask as a free fallback because their current official documentation marks these endpoints as premium.

## Display and licensing rule

A free tier can be limited to personal, internal, or non-display use. Provider data is used only when its configured account and terms permit the project's public dashboard. Operators remain responsible for their provider account terms.

## Five-bridge integration review (2026-10-19)

- `options_radar/optional_massive_research.py`: real Massive EOD REST adapter for **stocks and named OCC option contracts**, but fail-closed by default. An ordinary free individual key **does not authorize** non-display analysis, derived outputs, public charts or redistribution. Do not activate merely by setting a key. A separately documented compliant license and explicit operator approval are required (`licensed=True` / `MASSIVE_NONDISPLAY_LICENSE_CONFIRMED=true`). No project secret or licensed prices are shipped publicly.
- `options_radar/data_fabric.py::optional_independent_eod_research`: opt-in, internal-only Massive wrapper. No trade recommendation gate uses its output.
- `options_radar/sec_bulk_fallback.py` and `scripts/build_sec_filing_pulse.py`: bounded, offline official SEC submissions ZIP reader. Supply `--bulk-archive` / `SEC_BULK_SUBMISSIONS_ZIP`, `--bulk-cik-map`, plus operator attestation `SEC_BULK_OFFICIAL_ORIGIN_ATTESTED=true`; this feature does not download a ZIP to bypass SEC 403. SEC official reference: https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip . Operator must establish origin and archive currency; UI marks undated bulk results and does not imply fresh access.
- `options_radar/options_daily_outcome_shadow.py`: evaluates dated option close changes only when observed entry/exit daily OHLC records exist, not executable NBBO fills or realized profit.
- `options_radar/stock_walk_forward.py::coverage_gap_diagnostics`: shows true shortfall in completed 60-minute observation coverage without changing the 90% gate.
- `scripts/build_source_consensus_status.py`: publishes only a **source agreement status** (not Massive prices or derived agreement data). One Yahoo family must be shown as unverified consensus. The public UI does not imply multiple price sources or qualified OPRA.

No package installation, subscription, forced retry, unlicensed API scrape, synthetic quote, or weakening of options execution gates is permitted by this integration.

## Free options alternatives activated in code (2026-10-19)

- `scripts/build_free_options_sources.py` and `.github/workflows/free-options-sources.yml` check the public **FilingPulse API** health `/v1/health` for free without a key. To fetch historical filing event metadata, add personal `FILINGPULSE_API_KEY` through GitHub Actions Secrets (never in code or frontend). The workflow is capped to four CIK-matched companies × three endpoints once per weekday (≤12 authenticated requests per run, ~264–276 monthly). These are **third-party SEC-derived records**, not authenticated live SEC EDGAR responses; every record says so, and only original sec.gov archive links and correct CIKs reach the UI. An external provider alone never proves earnings surprise, dilution, price impact or options executable prices.
- The same daily job attempts **OCC daily open-interest** official CSV (`OCC_DAILY_OI_ENABLED=true`) with a 25 MB transfer limit, strict CSV schema and one previous-business-day request. Unknown/HTML/403/oversized data => `UNAVAILABLE`/reason, never a fabricated open-interest count. OCC's existing official **Volume Query** adapters already provide CALL/PUT aggregate volume context and are unchanged. OI is historical, not live trade flow.
- **Tradier** stock and option adapters were already installed (`options_radar/market_bars.py`, `options_radar/providers.py`, `scripts/preflight_tradier_free_live.py`); do not duplicate them. Broker account and token are required; **sandbox is 15 minutes delayed**, brokerage account can access real-time subject to entitlement. Tradier says personal API usage may not be redistributed on a public application unless partner-approved. Thus no account quotes are emitted from this daily public workflow and no trade orders are submitted.
- `Bortlesboat/qlib-options` is MIT, but captures **Yahoo** options snapshots and cannot backfill old history. The existing Yahoo-family snapshots already count as ONE source; adding another Yahoo client cannot solve independent source confirmation or OPRA execution access. Add only after confirming it improves source-preserving offline storage.
- FilingPulse is SEC-derived third-party metadata and OCC Open Interest is one-day context; neither can promote an option to V11 execution grade or turn a research CALL/PUT into an actionable contract trade.

References: https://filingpulse.io/docs.html ; https://docs.tradier.com/docs/faq ; https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/daily-open-interest ; https://github.com/Bortlesboat/qlib-options
