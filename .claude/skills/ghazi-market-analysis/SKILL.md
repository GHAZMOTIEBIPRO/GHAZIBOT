---
name: ghazi-market-analysis
description: Produce or review a GHAZI RADAR multi-timeframe reading for a stock, ETF or index (leaders like NVDA/AAPL/MSFT, SPY/QQQ, SPX) from reproducible computations only - per-frame trend (weekly/daily/4H/1H/15m/5m), frame agreement, levels with a stated method, conditional scenarios with invalidation, linked official news, and what data is missing and what that does to the reading. Use this whenever the task is an analysis card, a daily plan, a Telegram plan message, an Arabic explanation of a computed result, or a check that an explanation did not invent a price, level, news item or success rate - even if the user just says "analyse NVDA" or "why is SPY bullish".
---

# GHAZI market analysis

Code computes, and language explains what the code computed. Any number in a reading comes from `options_radar/daily_plan.py` (or another tested module) and is traceable to a bar. An explanation may restate it, compare it, or say what would change it. It may never produce a new number, level, news item or probability.

## Three layers, kept visibly apart

1. **Observed.**
   - Bars, with source, feed, the provider's bar time and the delay.
   - Levels measured on named bars, for example "prior-day high 201.3, bar 2026-10-28".
2. **Interpretation.**
   - Frame trend by a declared rule (close vs EMA20/EMA50).
   - Structure (higher highs/lows).
   - Agreement, counted as frames, not as a percentage.
3. **Scenario.**
   - "If a completed 1H bar closes above X, then Y; invalidated below Z."
   - Every scenario carries its trigger, its target basis (or "no measured level"), its invalidation and its horizon.
   - No probability is attached.

## Workflow

1. **Get checked bars** (skill `ghazi-data-quality`). Anything below `OK` stops the affected frames only.
2. **Build the plan** with `options_radar.daily_plan.plan_for_symbol`. Assemble the reading with `options_radar.analysis_card.build_card`. The card adds:
   - asset type;
   - data time and delay;
   - the linked news;
   - the missing-data list with its impact on the reading.
3. **Write the Arabic explanation** only from the card's fields. `analysis_card.explain_ar` is a deterministic template. If an LLM rewrites it for tone, pass it the card JSON as its only input, then check every number in its output against the card (`analysis_card.numbers_supported`).
4. **When a frame fails, show the frames that worked.** Say which frame is missing and what that removes. For example: "no 1H: intraday triggers cannot be confirmed; the daily levels still hold".
5. **When the options chain fails, the stock reading still stands.** The two are independent (AGENTS.md).

## Output contract (card)

```json
{"symbol": "NVDA", "asset_type": "STOCK", "source": "alpaca_iex", "feed_scope": "IEX only",
 "data_as_of": "2026-10-28T20:00:00+00:00", "delay_note": "completed bars only; nothing from the latest 16 minutes",
 "frames": {"daily": {"trend": "UP", "basis": "close vs EMA20/EMA50"}, "1h": {"trend": "UNAVAILABLE", "reason": "..."}},
 "agreement": {"frames_voting": 3, "largest_same_direction": 2},
 "levels": [{"name": "prior_day_high", "value": 201.3, "bar": "2026-10-28", "method": "high of the last completed session"}],
 "scenarios": [{"kind": "BULLISH", "trigger_level": 201.3, "invalidation": 199.9, "invalidation_basis": "prior-day high − 0.25×ATR14"}],
 "news": [{"date": "2026-10-28", "title": "...", "url": "https://...", "source": "Company IR"}],
 "missing": [{"item": "1h", "impact_ar": "..."}], "probability": null}
```

## Acceptance criteria

- Every number in the explanation appears in the card.
- Saved data is never called live. "As of" is the bar's end time.
- Agreement is never turned into a probability or a "confidence %".
- A scenario without a measured target says so; it never shows a made-up target.
- News items have a date and an official link, or they are not shown.

## Examples

**Pass:** "NVDA (IEX only, completed bars as of 28 Oct 16:00 NY):
- daily up (close above EMA20 and EMA50);
- weekly up;
- 1H unavailable, so the breakout trigger cannot be confirmed within the session.

The bullish scenario holds above 201.3 (prior-day high); it is invalidated below 199.9."

**Fail:**
- "NVDA is heading to 215". 215 is not in the card.
- "Probability of rise 72%".
- "Live price 203.1" taken from a saved file.
- Hiding that 1H was missing.

## Where things live

| Code | Role |
|---|---|
| `options_radar/daily_plan.py` | Frames, levels, scenarios |
| `options_radar/analysis_card.py` | Card contract, missing-data impact, Arabic template, number check |
| `scripts/build_daily_plan.py` | Provider → compute → output policy → owner-private sink |
| `tests/test_analysis_card.py` | Contract and the invented-number guard |
