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

## Available optional free-account private probe (2026-10-19)

A single manual GitHub Action, `.github/workflows/alpaca-private-probe.yml`, checks historical
Alpaca IEX stock bars and, optionally, **historical option aggregate bars** older
than the current UTC calendar day. This is based on Alpaca's documented Basic
history access; **indicative quotes are not OPRA NBBO**. No keys or source
prices are exposed to website users, and no bot alert is promoted.

To run: supply your own `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in
GitHub Secrets and set repository variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`
only if the connected account's terms actually permit this internal research use.
Otherwise the workflow reports `DATA_USE_PERMISSION_REQUIRED` and makes
**zero requests**. Historical options are reported as close-to-close *observations*,
never actual fills or realized returns. The manually dispatched workflow emits
only availability and verified-bounds metadata in private logs.

For SEC, `build_sec_filing_pulse.py --local-cik-map app/data/sec_cik_map.json`
lets an existing checked-in CIK map **nominate** issuer IDs only if the
official SEC ticker index or optional mirror is unavailable. The live SEC
`submissions/CIK...` response must verify both ticker and CIK before any
new official filing is published. An HTTP 403 or active cooldown remains
`UNAVAILABLE`, not an empty/positive issuer filing list. Follow SEC fair-access
requirements and contact the SEC webmaster for persistent blocks.

The Walk-Forward research report now includes counts of 60-minute
observations unavailable due to no post-signal bars, pending evaluation,
or other incomplete observations. These counts **never** modify the 90%
coverage gate, historical outcomes or claimed accuracy.

References:
- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
