# BLACK BOX — U.S. Options Data Provider Research

**Research date:** 2026-09-29
**Scope:** documented U.S. option-chain capabilities for a read-only intelligence/alert bot; no broker order or transaction functionality was reviewed.

> **Bottom line:** none of the researched providers supports the combination of **free + real-time OPRA-quality options data + public/multi-user redistribution** under ordinary self-service access. The current `FALLBACK_ONLY` state is therefore correctly non-production. Any claim of live option-flow intelligence must remain disabled until an entitled source and appropriate display/redistribution rights are independently confirmed.

## Comparison

| Provider | Verified useful fields | Free/low-cost boundary | Live / data-quality boundary | Public display / redistribution boundary | Recommended role |
|---|---|---|---|---|---|
| **Tradier** | Chain/quotes, bid/ask, OI, volume/last summaries, IV, Greeks | Brokerage account API access; sandbox is delayed | Production options are real-time for entitled brokerage account holders; sandbox is 15-minute delayed | Official FAQ limits ordinary API use to personal use; partner review is needed for application distribution | Best fit for a **private, account-linked** bot adapter; not an anonymous public dashboard feed |
| **Alpaca** | Quotes/trades, snapshots/chains, conditional IV/Greeks, trade/bar volume | Basic provides an **Indicative** feed | Free indicative options are 15-minute delayed and not actual OPRA; OI was not verified in reviewed docs | Official support answer says API data cannot be redistributed | Delayed/internal research only; do not use for OI-gated live alerts |
| **MarketData.app** | Chain/current quote snapshots, bid/ask, last, volume, OI, IV, major Greeks | Free: 24-hour delayed; Starter: 15-minute delayed | Real-time needs qualifying OPRA entitlement; no trade-level tape; historical IV/Greeks are null | Self-service plans are personal; public display/redistribution requires commercial/OPRA review | Strong **delayed/historical research** adapter if credit budgeting and licensing are accepted |
| **Intrinio** | Bid/ask, trades, IV, Greeks, OI, volume; REST/WebSocket where entitled | Trial/testing is delayed; low-cost plans are EOD/delayed | Realtime is entitlement-gated and current product material identifies it as Enterprise-only | Public display/redistribution needs feed-specific terms and an executed order form | Enterprise/entitled production option; not a free live source |
| **Polygon / Massive** | Chain/contract snapshots, quotes, trades, IV, Greeks, OI, market volume | Free supports EOD/reference/minute research; chain snapshots begin in paid tier | Starter/Developer chain snapshots are 15-minute delayed; real-time quotes are higher-tier | Consumer plans prohibit public display/redistribution without a commercial license | EOD/free research or a paid, licensed adapter; not free live public data |

## Architecture decision

1. **Keep the existing free path research-only.** Yahoo/YFinance or indicative data may support discovery, historical research, and explicitly delayed outputs; it must not create an execution-quality options alert.
2. **Do not make a provider key a silent feature toggle.** Provider readiness must continue to require documented bid/ask, timestamp, entitlement, OI/volume where used, and a valid freshness window.
3. **Default production target:** use the existing Tradier adapter only for a private, user-connected destination where its account entitlement and use terms are satisfied. The public Vercel dashboard must not display raw or provider-derived quote data until a compatible public-display license is documented.
4. **Best research upgrade:** MarketData.app has the broadest documented snapshot field set in this review, but its free tier is 24-hour delayed and self-service use is personal. It can improve delayed research once an account/key is supplied, not solve live public delivery.
5. **Do not use Alpaca as the sole OI source.** OI was not established in the reviewed official Alpaca option documentation; the system should retain OI as unavailable rather than synthesize it.
6. **No financial transactions.** All integrations remain read-only market-data inputs. The bot may emit a non-transactional, clearly labelled notification only after its separate destination and data-entitlement checks pass.

## Official source register

### Tradier

- https://docs.tradier.com/docs/market-data
- https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains
- https://docs.tradier.com/reference/brokerage-api-markets-get-quotes
- https://docs.tradier.com/docs/faq

### Alpaca

- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/real-time-option-data
- https://docs.alpaca.markets/us/docs/historical-option-data
- https://docs.alpaca.markets/us/reference/optionsnapshots
- https://docs.alpaca.markets/us/reference/optionchain
- https://alpaca.markets/support/redistribute-alpaca-api

### MarketData.app

- https://www.marketdata.app/data/options/
- https://www.marketdata.app/docs/api/options/quotes/
- https://www.marketdata.app/docs/api/options/chain/
- https://www.marketdata.app/pricing/
- https://www.marketdata.app/docs/api/cors/
- https://www.marketdata.app/education/options/opra-fees/

### Intrinio

- https://docs.intrinio.com/documentation/web_api/get_options_chain_realtime_v2
- https://docs.intrinio.com/documentation/web_api/get_options_chain_v2
- https://help.intrinio.com/options-faqs
- https://intrinio.com/options/options-realtime
- https://about.intrinio.com/terms

### Polygon / Massive

- https://massive.com/docs/rest/options/overview
- https://massive.com/docs/rest/options/snapshots/option-chain-snapshot
- https://massive.com/options
- https://massive.com/pricing
- https://massive.com/legal/market-data-terms-of-service
- https://massive.com/knowledge-base/article/how-can-i-redistribute-massives-market-data
