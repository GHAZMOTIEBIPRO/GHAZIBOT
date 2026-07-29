# SEC EFTS on hosted runners

The SEC full-text endpoint is optional in GHAZI Market Radar.

## Current behavior

- Requests identify the application through `SEC_USER_AGENT`.
- HTTP 429 and transient 5xx responses use bounded exponential backoff.
- HTTP 403 is not retried repeatedly because that can extend an IP-based block.
- The scanner continues when EFTS is unavailable.

## Active fallbacks

1. SEC latest-form Atom feeds.
2. SEC submissions and Company Facts APIs.
3. The last valid cached EFTS event set.

A successful GitHub Actions job does not prove EFTS availability. Check
`data/cache/sec_efts_status.json` for the latest probe result and HTTP status.

The SEC documents a maximum automated access rate of 10 requests per second.
The radar defaults to 8 requests per second or less.
