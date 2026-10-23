# Private market data activation

CODED: bounded, read-only Tradier stock/options access diagnostic; existing private
Alpaca historical IEX probe integrated in a single manual/on-change workflow.
This is not a live scanner, redistribution license, or evidence of profitable signals.

## Account setup (owner only)

Never paste tokens in chat, source files, public Actions inputs or browser JavaScript.
Use repository Settings > Secrets and variables > Actions.

### Tradier
- Secret `TRADIER_TOKEN`: production token from your own eligible brokerage account.
- Secret `TRADIER_BASE_URL`: `https://api.tradier.com` for production;
  `https://sandbox.tradier.com` for a sandbox token. Tokens are environment-specific.
- Variable `TRADIER_INTERNAL_DATA_USE_AUTHORIZED=true` only after confirming the
  account's terms permit this internal personal API use. This records permission;
  the software cannot grant rights or accept agreements for the owner.
- Run **GHAZI Private Market Data Access** using Run workflow.
- Inspect `private-source-access-metadata`: ACCESS_VERIFIED means identity and
  chain access, not freshness or trading readiness. Inspect separate quote checks.
  Both bid_date and ask_date must be within 120 seconds, not future. Last-trade time
  is never substituted. Outside market hours, stale quotes are expected.
- The probe only GETs market endpoints. It never places orders or opens accounts.
- Existing scanner execution gates stay unchanged; a successful probe does not
  enable public exports or make sandbox quotes live. Private continuous ingestion
  and delivery must be verified separately once an eligible account is available.

### Alpaca
- Secrets `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.
- Variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true` after applicable permission
  is confirmed. Existing private IEX/VCP workflow also requires its own delivery
  configuration; do not mark public redistribution permitted.
- Basic IEX is one exchange, not consolidated US volume. Indicative options do not
  qualify as actual executable OPRA quotes. No paid subscription is enabled here.

## Public website

Keep TradingView's embedded display and official catalyst sources. Personal API
prices must not enter public GitHub branches, artifacts, logs or site JSON. This
workflow publishes only fixed-label access metadata, booleans and diagnostic time.
A private report path or branch in this public repository is still public.

## Remaining candidates

ThetaData's free EOD data is for historical research, not current contract entry.
Its account/terminal and personal-use permission are prerequisites; do not install
an unconfigured terminal or publish its raw data. ib_async needs IBKR account data
entitlements and a persistent Gateway/TWS; GitHub Actions is not a persistent
broker gateway. No ThetaData or IBKR feed was activated by this change.

## Verified primary references (2026-10-23)

- https://docs.tradier.com/docs/market-data
- https://docs.tradier.com/reference/brokerage-api-markets-get-quotes
- https://tradier.com/pricing
- https://support.tradier.com/kb/guide/en/permitted-and-blocked-countries-CLzSa0D1rf/Steps/4997916
- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://thetadata.net/docs/Articles/Getting-Started/Subscriptions.html
- https://www.thetadata.net/subscriber-agreement
- https://github.com/ib-api-reloaded/ib_async

No external implementation copied. A standalone requests adapter avoids adding
an SDK dependency for three GET requests. No new recurring writer or cron.
