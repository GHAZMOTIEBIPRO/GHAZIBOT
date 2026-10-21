# Twelve Data readiness (prepared before any key exists)

**Status.**
- CODED, TESTED.
- No `TWELVE_DATA_API_KEY` is configured, so no request is made.

**Sources** (official pages read from a GitHub runner):
- Terms: https://twelvedata.com/terms (run 39529567535)
- Pricing: https://twelvedata.com/pricing.md (run 39566940801)

## What the free plan allows

| Item | Official text |
|---|---|
| Rate | "\| Basic \| $0/mo \| 8 (800/day cap) \| 8 (trial) \| US \| Real-time US equities, forex, crypto \|" |
| Daily cap | "Free and Basic plans add an 800-request/day cap on top of the per-minute limit" |
| Licence | "internal non-display usage only" |
| Individual plans | "personal research, hobby projects, learning, internal analytics for your own use ... Display and distribution are limited to internal personal use." |
| Business | "Business plans are required for any company, team, fund, or organization ... Business plans also unlock external display rights" |
| Credit weight | "most endpoints cost 1 credit per symbol; premium data (fundamentals, analysis) costs more." |
| WebSocket | "8 **trial** WS credits ... intended for evaluating streaming, not for production use." |
| Storage | "(g) Store or cache Data beyond permitted timeframes specified in the Documentation" is prohibited |
| Public display | "(e) Redistribute or provide external display of Data only if and as expressly authorized by a Redistribution Rights Add-On or separate written agreement" |

## What it means for GHAZI
1. **Internal research only.** Twelve Data numbers never reach the public site or Telegram, as raw prices or as derived analytics.
   - `public_guard` keeps the account-API family closed for public outputs.
   - `price_source_gate --public` refuses the key, because `public_display_derived` is RESTRICTED. The owner's confirmation cannot change that.
   - External display needs a Business plan (Venture or higher) or a written agreement. That is a paid service, so it is not pursued.
2. **Non-display.** Results feed internal research files (walk-forward, independent price check, agreement checks). They do not feed display panels.
3. **No persistent cache.** `RequestCache` keeps a response in process memory for at most one bar interval and writes nothing to disk.

## Credit budget (`options_radar/twelve_data_budget.py`)

| Engine | Symbols | Interval | Runs / day | Credits / day | Minutes per run at 8/min |
|---|---|---|---|---|---|
| index_etfs_15min (SPY QQQ IWM DIA) | 4 | 15min | 26 | 104 | 1 |
| large_caps_1h | 20 | 1h | 7 | 140 | 3 |
| watchlist_daily | 60 | 1day | 1 | 60 | 8 |
| independent_price_check | 8 | 1day | 4 | 32 | 1 |
| catalyst_price_band | 20 | quote | 1 | 20 | 3 |
| **Total** | | | | **356** | |

- **Allowance:** 80% of 800 = 640 credits a day, which leaves 284 credits of headroom.
- **Test:** `test_engine_plan_fits_the_free_plan_with_headroom` fails if a change to the plan stops fitting.

## Guards
- **`CreditGuard` (per process):**
  - Holds a sliding 60-second window. It waits for the window instead of exceeding 8 credits a minute, and stops after 65 s.
  - Holds a per-run allowance equal to the engine's planned credits.
  - When either limit is reached, it raises `QuotaExhausted`.
- **Provider answers:** HTTP 429, or an error whose message names credits, also raises `QuotaExhausted`.
- **Failure handling:** `QuotaExhausted` is a `RuntimeError`, so the existing provider fallbacks treat it as an unavailable source.
  - The engine reports the source as unavailable instead of publishing partial or stale numbers.
  - The site keeps working: it already shows "unavailable" states from the Data Hub.
- **Configuration:**
  - `TWELVE_DATA_ENGINE` selects the engine's allowance (default `watchlist_daily`).
  - `TWELVE_DATA_CREDITS_PER_MINUTE` / `_PER_DAY` override the plan figures on a different plan.

## When the key is added
1. **Add the secret.** GitHub → repository → Settings → Secrets and variables → Actions → New repository secret. Name it `TWELVE_DATA_API_KEY`.
2. **No restart needed.**
   - Nine workflows already pass the secret: classical-direction-radar, explosion-options-crosscheck, fast-explosion-radar, options-contract-radar, options-radar, publish-classical-direction, stock-radar, stock-watch-charts, and the probe.
   - The source gates in four of them (explosion-options-crosscheck, options-contract-radar, publish-classical-direction, stock-radar) read `HAS_TWELVE_DATA_API_KEY`.
   - `price_source_gate` counts the key for internal research, because `automated_access` and `internal_analysis` are VERIFIED.
   - The next scheduled cycle uses it.
3. **Public outputs stay blocked** unless a plan with external display rights is bought.

## Tests
`tests/test_twelve_data_budget.py` uses fixture payloads only, no network:
- the plan fits the allowance;
- environment overrides;
- waiting on the minute window;
- the run allowance;
- the wait limit;
- in-interval dedupe;
- HTTP 429 and credit errors;
- no disk writes;
- the adapter path through `market_bars._twelve_data` with a fake HTTP response.
