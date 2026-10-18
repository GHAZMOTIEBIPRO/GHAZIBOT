# GHAZI RADAR — independent market-price evidence

**Rule:** matching numeric prices do not constitute price consensus unless the
providers represent different upstream families **and the exact same completed
candle / NY trading session**.

The stock fabric now reports:
- \`source_count\`: transport successes, which may contain multiple Yahoo clients
- \`independent_source_count\`: vendor families present in the raw result, including stale ones
- \`matched_bar_independent_source_count\`: *same-candle* independent vendors
- \`consensus_pass\`: true only when at least two distinct matched families agree within the configured divergence threshold
- \`unmatched_bar_provider_count\`: vendors whose latest bar belongs to another session/minute
- \`bar_start_or_session\`: exchange-session calendar date or intraday provider bar start, not wall-clock run time
- \`quote_execution_eligible\`: always false; this is a bar/research diagnostic, not NBBO/OPRA

The feed selector returns one intact series; it NEVER constructs a median
synthetic price or manufactures a live quote. A stale quote does not outrank a
newer one simply because its vendor has a higher static quality score. With
only Yahoo configured (current default), independent confirmation remains
FALSE, even if YahooQuery and YFinance both succeed.

Alpaca Basic (if **user independently activates a free account and provides
credentials as GitHub secrets**) covers IEX equities, not the whole SIP.
The existing \`market_bars.py\` Alpaca adapter and provider preflight are
already installed — no second adapter is needed. Its Basic option feed is
INDICATIVE, NOT OPRA, and may NOT lift options V11.
There is no requirement to buy credentials, change tiers, scrape paywalls or
publish raw licensed quote content publicly.

**Warning:** stock bar history adjustments (raw vs split-adjusted) differ by
provider; even same NY session agreement must be reviewed around splits.
Live option recommendation logic is not changed.

References:
- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
