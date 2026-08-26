# BLACK BOX V9 — Realtime Options Intelligence

## Why this exists

The existing options radar remains valuable as a batch/cold-path scanner, catalyst checker, provider-consensus layer, OI follow-up, and self-grading system. It is not the right hot path for a 0DTE or pre-explosion alert because scheduled polling can be late and snapshot Volume/OI cannot reconstruct execution intent by itself.

V9 adds a separate realtime hot path instead of deleting the proven batch path.

## Research inputs

The design was checked against:

- Intrinio realtime options SDK and OPRA feed examples: callbacks can receive every trade plus unusual activity (block, sweep, large, unusual sweep), and Intrinio explicitly recommends very short callbacks feeding a queue because the options universe is high-throughput.
- Intrinio unusual-activity API: provider-aggregated events include timestamp, type, total premium, size, contract, bid/ask at execution, sentiment, and underlying price at execution.
- Tradier streaming documentation: authenticated WebSocket/HTTP streams can carry trade, quote, timesale and related events; production brokerage data is realtime while sandbox data is delayed.
- Cboe Trade Alert/LiveVol product model: professional flow analysis emphasizes directional trades, complex orders, unusual activity and volatility context.
- Joevue123/unusual-options-scanner: a useful snapshot baseline/volume-delta design, but its own README correctly calls burst detection "sweep-like" without per-trade timestamps/exchange data.
- samir-shah-ahmed/trading-signal-scanner: persist outcomes and judge signals by later observed performance rather than trusting a score.
- Intrinio's official Python SDK trade qualifiers: spread, buy/write, synthetic and multi-leg qualifiers are used to flag complex-order risk.

## Architecture

### Hot path — V9

`Intrinio OPRA WebSocket -> tiny callbacks -> bounded queue -> parent-order clusterer -> thesis engine -> Telegram thesis card`

Properties:

1. **Fail closed on latency**: a confirmed thesis requires realtime evidence and a fresh event age.
2. **Parent-order reconstruction**: trade fragments in a short contract/time/price window are clustered instead of counted as independent institutional decisions.
3. **Provider aggregate de-duplication**: an Intrinio unusual-activity event can overlap raw trade callbacks; premium is not intentionally counted twice.
4. **Complex-order risk**: OPRA/Intrinio qualifiers associated with spreads, buy/writes, synthetic combinations and multi-leg executions block a clean single-leg confirmation when they dominate.
5. **Evidence grade, not fake probability**: V9 emits A+/A/B/C. It never says 94/100 means a 94% win probability.
6. **Thesis state machine**: `WATCH -> BUILDING -> CONFIRMED -> EXTENDED/FAILED`.
7. **One evolving Telegram card**: once a thesis has a Telegram message, later state transitions edit that message rather than flooding the chat with duplicate contract alerts.
8. **Price-response check**: the underlying is classified as lagging, confirming, extended or diverging relative to the flow.
9. **Opposing-flow veto**: a bullish thesis can be failed when materially stronger bearish parent-order premium appears, and vice versa.
10. **Raw outcome trail**: thesis transitions are persisted as JSONL for later replay and empirical calibration.

### Cold path — existing V8

Keep V8 for:

- provider consensus and options-chain breadth
- catalyst/news checks
- OI T+1 follow-up
- slower repeat-flow memory
- self-grading/outcomes
- fallback research when realtime entitlement is unavailable

V9 should not replace the cold path. The two systems answer different latency questions.

## Runtime

Install:

```bash
pip install -r requirements-realtime.txt
```

Required:

```bash
export INTRINIO_API_KEY=...
export INTRINIO_OPTIONS_SOURCE=realtime
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
```

Optional watch universe:

```bash
export OPTIONS_REALTIME_SYMBOLS=SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA,META,AMZN,GOOGL,AVGO
```

Run:

```bash
python -m scripts.run_realtime_options_intelligence \
  --wait-for-market \
  --until-market-close
```

The GitHub Actions workflow `options-realtime-intelligence-v9.yml` provides a no-new-server bridge. It requests realtime OPRA only and deliberately refuses to silently downgrade the hot path to delayed data.

## Important limits

- Realtime OPRA/Intrinio entitlement is a data-provider requirement, not something code can manufacture.
- Bid/ask execution side and provider sentiment do not prove Buy-to-Open. OI follow-up remains necessary.
- Parent-order reconstruction is conservative inference unless the provider has already aggregated a sweep/block.
- GitHub Actions is a transitional runtime. A persistent worker/VPS/container is preferable for lowest-latency production because scheduled job start time can be delayed.
- No flow scanner guarantees price direction or option profitability. IV, theta, spread and event risk still matter.
