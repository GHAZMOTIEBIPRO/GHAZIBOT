# GHAZI RADAR — Primary US index and major-company options focus (2026-10-30)

User-defined focus for scanning, historical-research charts and Telegram opportunities.

## Priority 1 — index technical direction
- SPX — S&P 500 cash index
- NDX — Nasdaq-100 cash index
- SPY — S&P 500 exchange-traded ETF
- QQQ — Nasdaq-100 exchange-traded ETF

Existing index-direction engine already handles these four separately (completed 1D/1H/15m/5m research candles). Never equate SPY to SPX or QQQ to NDX and never reuse their price levels interchangeably.

## Priority 1 — US-listed shares / options
TSLA, AMD, MU, NVDA, MSFT, BABA (ADR), GOOG, GOOGL, META.

GOOG and GOOGL are distinct traded share classes, **not** synonyms for a single OCC option symbol. AMD is intentionally included once.

## Priority 2 — other liquid mega/large-cap shares
AAPL, AMZN, AVGO, NFLX, PLTR, JPM, COST, ORCL, QCOM, XOM, and the existing broader curated company universe.

## Behavior
- The independent options-contract scanner prioritizes SPY/QQQ + stocks above when allocating bounded discovery slots.
- SPX/NDX remain separate index research products; SPXW/NDXP are option roots, not ETF or stock substitutes. A real quote/bar entitlement and valid contract identity are needed to activate these index option contracts.
- The large-company CALL/PUT classical direction path searches the named stocks first; all previous guards and broad coverage stay intact.
- Fixed research-only stock charts now request each named stock in the configured fixed watch.
- Focus status is exposed in the options payload: selected vs not selected, **not** as proof of valid quotes or recommendation readiness.
- Every actionable alert remains gated by V11, verified option contracts, bid/ask/OI/volume, freshness, rights and evidence. The focus list changes priority, never trade direction/score/threshold.
- No market-data vendor or publication license is activated here. The public Yahoo data gate continues to block automated-public redistribution; a watchlist is not a working options candle feed.
- Gamma and flow fields must explicitly say UNAVAILABLE when provider-grade options trade/quote data do not exist. Do not label snapshot activity a sweep.
- Watchlist stocks may be omitted from an actual cycle if optionability, source licensing, quotas, or other safety gates block them.
- Do not claim outcomes from underlying touches; contract premium levels need independently stamped contract prices, not a price-mapped simulation.

## Verification
Run `pytest -q tests/test_focus_universe.py tests/test_optionable_universe.py tests/test_classical_stock_direction.py tests/test_stock_watch_charts.py` before merging. Confirm both CI and runtime metadata.
