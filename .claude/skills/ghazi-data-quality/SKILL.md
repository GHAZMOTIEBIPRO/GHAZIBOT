---
name: ghazi-data-quality
description: Check GHAZI RADAR market data before anything is computed from it - source and feed identity, freshness (provider time vs our clock), gaps, duplicate or out-of-order bars, OHLC consistency, completed vs still-forming bars, time zones and XNYS sessions, split/adjusted vs unadjusted prices, and whether enough history exists for an indicator. Use this whenever a task touches bars, candles, OHLCV, prices, indicators (EMA/ATR/RSI/VWAP), Alpaca/IEX/SIP feeds, options_radar/ohlcv_quality.py, options_radar/daily_plan.py, bar_providers.py or bar_aggregation.py, or when a number on the site or in Telegram looks wrong and you need to tell a data fault from a code fault or a source outage.
---

# GHAZI data quality

Compute nothing from data you have not checked. A wrong bar breaks everything built on it, so it has to be caught before it becomes a level, a trend or an alert. The first question about any odd number is which of three things went wrong:

| Code | Meaning | Who fixes it |
|---|---|---|
| `SOURCE_UNAVAILABLE` | The fetch did not return data: no key, a policy gate, HTTP error, timeout. | Configuration or the provider; never "fill in" values |
| `DATA_ERROR` | Data arrived but breaks a rule: negative or zero price, high < max(open, close), duplicate timestamp, out of order, negative volume. | Drop or repair the bad rows with a recorded reason, or reject the series |
| `INSUFFICIENT_HISTORY` | The data is valid but too short for the requested indicator. | Report which frames are missing; compute the frames that do qualify |
| `COMPUTE_ERROR` | Valid, sufficient data gives a result that disagrees with the reference implementation. | Our code |

These four are kept apart in every output (`options_radar/ohlcv_quality.py` returns the code). One series with one bad row is a `DATA_ERROR` for that series, not a source outage. A missing frame does not stop the frames that are fine.

## Workflow

1. **Identify the source.** Record:
   - provider;
   - feed (`iex` = one exchange, `sip` = consolidated tape);
   - adjustment (`split`, `all`, `raw`);
   - request window;
   - the provider's own bar timestamps.

   Two transports of the same origin are one source: yfinance and yahooquery are both Yahoo.
2. **Run the row rules** with `options_radar.ohlcv_quality.check_bars`. It applies the pandera schema when pandera is installed and the same rules in plain Python otherwise. The rule codes are identical in both.
3. **Separate completed from forming bars.**
   - A bar counts only once its end is at or before the as-of time, which is the provider time minus its delay.
   - Daily bars count only after the XNYS session close, early closes included (`exchange_calendars`).
   - The current session is never "yesterday".
4. **Check adjustment.**
   - On unadjusted data, a close-to-next-open jump near a split ratio (2:1, 3:1, 1:10 …) is flagged `SPLIT_SUSPECT`.
   - On split-adjusted data the same jump is a real gap.
   - Never mix adjusted daily bars with unadjusted intraday bars in one level.
5. **Check history depth before indicators.**
   - EMA50 needs 50 completed bars.
   - ATR14 needs 15.
   - A weekly trend needs completed ISO weeks.
   - Below that, the frame is `INSUFFICIENT_HISTORY` with "has N, needs M".
6. **Check freshness against the provider's time**, never against `now()` on our side.
   - Last-trade age is not quote age.
   - A file written a minute ago can hold a week-old bar.

## Expected differences (not errors)

- **IEX vs SIP volume.** IEX volume is a few percent of SIP volume, and the IEX high/low can sit inside the SIP range. Label the scope ("IEX only, partial volume") and don't flag it.
- **Gaps from missing trades.** Alpaca emits a minute bar only when a trade happened. A missing bar is "no trade", not a data fault.
- **Missing warm-up bars.** A reference indicator library seeds differently in its first bars. Compare after the declared warm-up only.

## Output contract

`check_bars(...)` returns:

```json
{"status": "OK | DATA_ERROR | SOURCE_UNAVAILABLE | INSUFFICIENT_HISTORY",
 "issues": [{"code": "HIGH_BELOW_BODY", "rows": 1, "sample": ["2026-10-27"]}],
 "completed": 249, "forming": 1, "adjustment": "split", "feed": "iex",
 "split_suspects": [], "history": {"have": 249, "need": 50}, "last_completed_end": "2026-10-28T20:00:00+00:00"}
```

## Acceptance criteria

- Every published level names its source, feed and the bar it was measured on.
- No forming bar enters a "completed" frame.
- A rule violation never silently disappears. Rows are dropped only with a code and a count.
- `SOURCE_UNAVAILABLE` is never shown as "no movement" or as zero.

## Examples

**Pass:**
- 252 daily bars, one 2026-10-28 bar with `high < close`. The result is `DATA_ERROR` with `HIGH_BELOW_BODY` (1 row).
- The other 251 bars still give a valid daily trend.
- The bad row's date is listed.

**Fail:**
- A plan computed from those same 252 bars that reports the 2026-10-28 high as "resistance".
- A "stale data" warning measured from the file's `generated_at` instead of the last bar's end.
- Calling 18 IEX intraday bars "missing data" when the SIP tape shows trades. The bars exist; IEX simply has no prints there.

## Where things live

| Code | Role |
|---|---|
| `options_radar/ohlcv_quality.py` | Rules, codes, completed/forming split, split detection, history check |
| `options_radar/daily_plan.py` | Consumes checked bars, so frames say why they are unavailable |
| `options_radar/bar_providers.py` | Alpaca bars with feed and adjustment recorded |
| `options_radar/bar_aggregation.py` | 15m/1H/4H built on XNYS boundaries |
| `tests/test_ohlcv_quality.py` | One test per rule, plus parity with the pandas-ta-classic reference |
