# GHAZI CORE Ω — FREE-DATA MARKET STRATEGY (30 Oct 2026)

## Verified providers and limitations
- Alpaca Trading API Basic: IEX real equity bars (one exchange, not full SIP), indicative derivative options quotes and delayed option trades. Official API: https://docs.alpaca.markets/us/docs/about-market-data-api
- Option contract reference: https://docs.alpaca.markets/us/reference/get-options-contracts — open interest may be missing or as-of a prior date.
- Option chain: https://docs.alpaca.markets/us/reference/optionchain — indicative quotes are modified, **not executable OPRA NBBO**.
- Option historic bars: https://docs.alpaca.markets/us/reference/optionbars — older than latest 15 minutes on Basic. True OHLCV observations, but not an intraday execution-grade feed.
- Alpaca public redistribution is explicitly prohibited: https://alpaca.markets/support/redistribute-alpaca-api ; no public prices, derived levels, contract chains, GEX walls or Telegram-group quote redistribution.

## Strategy rules and data lineage
**Underlying stage** (SPY/QQQ and equities TSLA AMD MU NVDA MSFT BABA GOOG GOOGL META):
1. Validate genuine completed 5-minute bars and prior completed NYSE daily candles. Reject negative, future, unfinished, malformed bars.
2. Levels: previous completed session high/low, previous 5 sessions' extremes (not calendar week), first completed 30-minute opening range, observed session VWAP from 5m IEX volume. Never call IEX full-market volume.
3. Research CALL: completed last close > opening range high, above IEX VWAP, EMA9 > EMA21. Research PUT: mirrored. All other configurations WAIT. Chart interpretation is not options premium movement.
4. Only after direction, inspect eligible OCC-symbol contracts 1–7 DTE SPY/QQQ, 1–21 DTE shares, delta magnitude 0.25–0.65, OI >=200, spread <=12% of ask, valid timestamp <=180 sec. These are **research filters only**; indicative feed disables execution.
5. Call/put gamma wall proxy: sum of OI * gamma * 100 shares * spot^2 * 0.01 at each strike, signed put-negative by convention; require >=20 covered contracts, >=70% joint coverage, dated OI <=4 calendar days. NEVER claim dealer inventory or a verified gamma flip. Snapshot trade size is not daily option volume or aggressor identification.
6. No generated option OHLCV, no synthesized sweep, no inferred execution price, no calculated P&L without executable trade evidence.
7. V11 remains authoritative: the free research engine produces WATCH_RESEARCH_ONLY or WAIT, never order or final trade recommendation. SPX/NDX cash indices are *not* SPY/QQQ. SPX and NDX options require a separately licensed true index/OPRA feed.

## Private automatic bot wiring
- New module `options_radar/core_options_strategy.py` is offline/pure.
- `scripts/run_focus_options_private.py` runs inside the existing owner-only `.github/workflows/private-market-scan.yml` (three session checkpoints on weekdays), never a public publishing workflow.
- No account/network access unless ALL are set in GitHub:
  - secrets `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`
  - repository variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`, only if the account's terms genuinely permit this purpose
  - repository variable `DATA_TERMS_CONFIRMED` includes `alpaca` once terms are verified
- Credential/rights setup requires owner action; no secrets or quote data are copied from a ChatGPT account connection into GitHub.
- JSON in `data/live/focus_private_strategy_health.json` contains **only** allowed metadata: per-symbol data availability and watch counts, never source prices, contract identities, raw quote data, or keys. It is written only under the GitHub runner's temporary directory; NOT committed, cached, uploaded, or published to bot-state.
- An optional research-status message (at scheduled checkpoints) is delivered through `options_radar.output_policy.deliver_private` only to the authenticated owner's one-to-one Telegram chat after setting `ALPACA_PRIVATE_ALERTS_AUTHORIZED=true` and the existing owner-chat credentials. No public channel, OPRA claim or execution signal.
- The module returns 0 execution-authorized signals on indicative quotes. A verified OPRA entitlement and legal redistribution permission would require separate review before changing this gate.

## Requirements for moving to real options alerts
- Confirm Alpaca API ownership and internal account entitlement; do not mislabel indicative as real-time OPRA.
- For real option execution, obtain licensed execution-grade NBBO and order-side prints with timestamps, true contract OHLCV and today's volume/OI provenance; for gamma include full strike/expiry chain and documented assumptions.
- Confirm source rights for any Telegram or public-site distribution; private internal dashboards can have different rights from public publication.
- Backtest using out-of-sample sessions with fees/slippage and provider delay; measure false positives, fill feasibility and time-of-signal. Do not target arbitrary accuracy percentages.
- Always show DATA_BLOCKED, WAIT, WATCH_RESEARCH, or verified execution state explicitly.

## Acceptance tests
`pytest -q tests/test_core_options_strategy.py tests/test_focus_bot_status.py tests/test_optionable_universe.py`
