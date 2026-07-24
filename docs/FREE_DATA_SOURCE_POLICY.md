# Free Data Source Policy

The radar uses only sources whose public documentation permits programmatic access.

## Enabled without private credentials

- SEC EDGAR public APIs and feeds, with a descriptive User-Agent and fair-access throttling.
- openFDA public API.
- Nasdaq public market-movers response as best-effort universe discovery.
- Yahoo/yfinance as an unofficial research fallback, explicitly labelled as such.
- U.S. Treasury public daily yield-curve feed for slow-moving macro context.

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
