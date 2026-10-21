# Alpaca Basic IEX — private-only VCP after-hours path

## What changed and why

Yahoo automated stock history remains blocked in `source_permissions.py`, and the existing public `stock_watch_charts.json` correctly reports `SOURCE_TERMS_BLOCKED`. A GitHub repo existing or a free account **does not** grant broad market-data publication permissions.

Official source documentation:

- [Alpaca Basic / free market coverage](https://docs.alpaca.markets/us/v1.1/docs/about-market-data-api): U.S. stock IEX feed only; not a consolidated NYSE/Nasdaq/SIP tape. Historical APIs have subscription-specific freshness limits and 200 API requests/min on Basic.
- [Official historical stock bars endpoint](https://docs.alpaca.markets/us/reference/stockbarsingle-1): `/v2/stocks/{symbol}/bars`, `feed=iex`, `timeframe=1Day`, explicit timestamps, bounded pagination.
- [Alpaca IEX vs SIP](https://docs.alpaca.markets/us/docs/market-data-faq): venue-only volume is substantially different from consolidated market volume and should not be interpreted as market-wide RVOL.

## New execution: isolated after-market job

- `.github/workflows/alpaca-iex-vcp-private.yml` is a **dedicated owner** of `bot-state/runtime/public/data/alpaca_iex_vcp_health.json` and `bot-state/state/alpaca/vcp_private_delivery.json`.
- Schedule **01:30 UTC Tuesday–Saturday** (covers the previous Mon–Fri U.S. session); also manual dispatch and a smoke run after code changes. GitHub schedules are not guaranteed exact and holiday runs may have no data.
- `scripts/alpaca_vcp_private.py` requests at most 8 named stocks; `feed=iex` only, maximum two pages per name, finite timeout, no retry on forbidden responses, no other price providers. Completed daily bars are filtered to strictly **before current New York date**, ensuring no still-forming daily bar gets a VCP label.
- Reuses `vcp_trend_shadow(frame, source_family="alpaca_iex")` without confusing IEX with Yahoo or SIP.
- Public state contains **only non-price operational metadata**. No symbols, OHLC, pivot, VCP stage, or market prices in GitHub output.
- The website's source-truth pane displays the operational status and explicitly states that raw or derived price-based data is not published to visitors.
- A single private Telegram **research WATCH** message per latest completed source session is possible only if authorized and the resulting stage is `TIGHT_WATCH`. This is not a production option signal, not broker order submission, and contains no prices.

## Account-side prerequisites (explicit, not silently bypassed)

1. Alpaca API credentials must be provisioned in GitHub repository Actions secrets `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. These may be paper/live market data credentials, subject to the user's market-data agreement.
2. **Only if the provider/account contract actually permits this private non-display use**, repository variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true` can be enabled. Missing credentials or variable -> **zero Alpaca HTTP requests** and a published blocked reason; this variable is not a substitute for permission.
3. Separate explicit permission for receiving derived securities research via a **private Telegram destination** must be verified and `ALPACA_PRIVATE_ALERTS_AUTHORIZED=true` set. Defaults to **false**. Without it, no ticker list or derived signals ever leaves the computation into Telegram or public artifacts.
4. Existing `TELEGRAM_BOT_TOKEN` and a valid existing Telegram destination must work for private alerts. No credentials, token values, or chat IDs are copied to public state.

## Important limits

- Basic free IEX is **not** full market consolidated volume. Relative volume and compression can diverge materially from SIP. Treat `TIGHT_WATCH` as indicative and low coverage; never promote to `CONFIRMED` or a CALL/PUT contract recommendation from this one source.
- Stage calculations are exploratory heuristics with no calibrated probabilities. Never claim positive returns, hidden dealer flows or insider identification.
- No new source is automatically added to `stock_watch_charts.json`; it still belongs to the existing chart-data rights owner and it must **not** republish Alpaca price bars.
- A git merge or Vercel READY proves the software exists, **not** that authorization, credentials, IEX data, Telegram receipts or an actionable market signal have been observed. Inspect public status and saved private message_id for the latter.
