# BLACK BOX V10 — Unified Thesis Engine

V10 turns the standalone bot from separate scanners into a gated decision-support thesis. It does not accept TradingView/Sniper webhooks and it never submits broker orders.

## Decision chain

`market candidate -> catalyst/source policy -> 1D/1H/15m classical alignment -> catalyst reaction -> contract quality -> flow evidence -> hard gates -> mobile thesis card`

## Thesis states

- `WATCH`: catalyst exists but price/chart confirmation is incomplete.
- `BUILDING`: chart or price reaction is developing in the catalyst direction.
- `CONFIRMED`: multi-timeframe chart, catalyst source and price reaction align.
- `EXTENDED`: direction may remain valid but price is too extended to chase.
- `FAILED`: chart/price/source evidence conflicts with the thesis.

## Evidence grades

V10 uses categorical evidence grades (`A+ / A / B+ / B / C / F`), not a pseudo-probability such as `94/100`. A grade is never a promised win rate.

The mobile card separates:

- Chart grade
- Catalyst/source grade
- Timing/reaction grade
- Contract grade
- Flow grade
- Data confidence (`LIVE / ACCOUNT / RESEARCH / UNAVAILABLE`)

## Data-confidence gate

A contract can be displayed for research while still being blocked from execution-ready status. Yahoo, delayed, indicative and sandbox sources are `RESEARCH`. Only a qualifying live/account feed plus a liquid contract can set `manual_execution_ready=true`.

Even then, the user must verify the live quote in the broker before manual execution.

## Chart integration

The existing classical direction radar supplies completed-bar 1D/1H/15m evidence. A catalyst does not override an opposite multi-timeframe chart: direct chart/catalyst conflict is a hard `FAILED` gate.

## Catalyst reaction

When an explicit `move_since_catalyst_pct` exists, V10 uses it. Otherwise it labels the response as a conservative proxy based on the fast radar's price move, relative volume and market stage. It never invents a news-timestamp price.

## Options

Contract quality and flow evidence are separate concepts. A good bid/ask, delta, volume and OI do not prove institutional buying. Realtime trade-level flow remains a separate V9 capability and becomes execution-grade only when a licensed realtime feed is actually configured.

## Mobile output

Telegram is optimized for a quick manual review:

1. Symbol, CALL/PUT, state and overall evidence grade.
2. Why now.
3. 1D/1H/15m chart alignment.
4. Trigger/invalidation.
5. Catalyst source/link.
6. Best aligned contract when available.
7. Data confidence and execution-readiness warning.

V10 is a decision-support system, not an autonomous trading system.
