# GHAZI RADAR 5-minute index research confirmation

Actual provider 5-minute candles are fetched ONLY for ^GSPC, ^NDX, SPY
and QQQ through existing bounded Yahoo research transport. No fake 5m bars
reconstructed from 15-minute or daily candles.

Completed-candle rules:
- Explicit NY provider timezone; source start + 5m must precede current time.
- Same NY trading session and max 20m elapsed from provider bar-start.
- Missing, old or divergent 5m for SPX/NDX forces homepage WAIT.
- Hourly and 15m candles remain subject to their existing closed-bar rules.
- All readings remain research-only, never OPRA/NBBO or execution authority.

Existing index-radar GitHub Actions job remains the ONLY writer.
Yahoo remains one unofficial provider and does not increase independent
source confirmation. No additional keys, paid providers or schedulers.

Reference: https://github.com/ranaroussi/yfinance