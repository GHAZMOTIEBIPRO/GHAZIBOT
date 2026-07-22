# Data-source audit (2026-07-22)

The scanner is source-aware. It never labels all free data as real-time and it
does not scrape websites whose terms prohibit automation.

| Source | Free access | Useful fields | Limitation | Project use |
|---|---|---|---|---|
| Yahoo Finance via yfinance | No API key | chain, bid/ask, volume, OI, IV, history | Unofficial; personal/research use; freshness varies | Default fallback |
| MarketData.app Free Forever | 100 requests/day | volume, OI, IV, Greeks, historical chains | At least 24-hour delayed on free plan | Optional provider/backtesting |
| Tradier Sandbox | Developer token | delayed chain, volume, OI, bid/ask | Delayed; sandbox Greeks unavailable | Preferred free developer provider |
| Tradier Brokerage | Eligible account | real-time options and Greeks | Brokerage account required | Production provider |
| Alpaca Basic | Free account | option quotes and Greeks via indicative feed | Trades delayed and quotes modified; no replacement for OI/volume | Optional enrichment |
| Webull OpenAPI | App/account | option snapshots and tick side | Real-time OPRA non-display subscription required | Future adapter |
| Cboe delayed quote dashboard | Manual | delayed chain, IV, Greeks, OI | Automated extraction explicitly prohibited | Manual verification only |
| Alpha Vantage options | API | realtime/historical options | Options functions are premium | Excluded from free mode |
| SEC EDGAR | Free official API | filings and company facts | Not an options-flow feed | Future catalyst enrichment |

## Meaning of flow

Free chains usually expose snapshots, not the full OPRA trade tape. The project
separates:

- **Vol/OI evidence:** daily volume divided by prior open interest.
- **Aggressor proxy:** last trade near ask/mid/bid when snapshot fields permit.
- **Confirmed sweep:** never claimed by free mode. Confirmation requires
  tick-by-tick trades, contemporaneous NBBO, exchange/condition codes, and split
  order reconstruction.

`NEW_INDEPENDENT_SETUP` is a deterministic research alert, not proof that an
institution opened the position.
