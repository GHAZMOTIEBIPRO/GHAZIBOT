# GHAZI RADAR — GitHub 50 project inventory and safe incorporation (2026-10-22)

Source-of-truth interactive list: [public/github-projects.html](../public/github-projects.html), 50 exact *user-provided labels* with 34 resolved original repository paths, 16 unresolved generic labels. The registry [public/github-projects.js](../public/github-projects.js) owns filtering, license notes, and the status of each candidate relative to **our codebase**, not an assertion that a 3rd party's outputs are profitable.

## New, functional integration in this change

| Public methodology / project | Integration | Files | Limits |
| --- | --- | --- | --- |
| [Qullamaggie Breakout Scanner](https://github.com/VladPetrariu/Qullamaggie-breakout-scanner) — MIT | Independent *conceptual* factors: near previous 55 daily highs, ATR contraction, daily volume dry-up | [options_radar/vcp_minervini_shadow.py](../options_radar/vcp_minervini_shadow.py), stock watch chart publisher, terminal stocks cards | No upstream code copied, no requests to GitHub or Yahoo added, no real-time or independent provider confirmation |
| [Stock Screener](https://github.com/xang1234/stock-screener) — Apache-2.0 | Independent closed-bar EMA20 > EMA50 and close above both; no heavyweight Celery/PostgreSQL/React duplication | Same VCP/Minervini shadow, read-only in stock research UI | Does **not** implement 80+ filters or inherit their accuracy; independent implementation only |
| [Stock Indicators](https://github.com/facioquo/stock-indicators-dotnet) | Source reference updated from former `DaveSkender/Stock.Indicators` owner to `facioquo/stock-indicators-dotnet` | GitHub 50 catalogue | No .NET dependency added to the existing Python application |
| [sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader) | Accurate repository link and SEC fair-access context | GitHub 50 catalogue | Existing [EdgarTools](https://github.com/dgunning/edgartools) research adapter remains unchanged; SEC 403 **not bypassed** |

The *new* factors use **only already-acquired completed daily candles**, no new fetch path. Each selected issuer is analyzed without the current incomplete daily candle, and the result has **no execution authority, no buy/sell classification, no CALL/PUT, no asserted probability, and no independent source confirmation**. If Yahoo automation permission is not granted, `scripts/build_stock_watch_charts.py` retains its existing rights gate and will not produce a fabricated live signal.

### Factor definitions (non-predictive)

- Last close above EMA20 above EMA50 on at least 70 valid ordered daily bars.
- Within 0.5% above to 6% below the *prior* 55-session high (latest bar excluded from that peak).
- Average true range (14 most recent completed daily ranges / prior 14) <= 0.85.
- Mean daily volume (last 10 complete bars / preceding 30) <= 0.85.
- Four factors -> `TIGHT_WATCH` (visual research watch **not a buy signal**); two or three -> `DEVELOPING`; otherwise `NO_SETUP`; missing/malformed -> `INSUFFICIENT`.
- No calibrated edge has been demonstrated for these thresholds; do not interpret a label as forecast, setup success probability or contract suitability.

## Important candidates *not* directly ingested

| Project | Why not copy/use its feed directly | Safer path |
| --- | --- | --- |
| [GammaGrid](https://github.com/gammagrid/gammagrid) | AGPL-3.0 integration obligations; upstream data unofficial/delayed; no dealer-position ground truth | Existing independent `gamma_heatmap_research` remains display-restricted, manual gate |
| [Gex-Multi](https://github.com/itsfabtrading/Gex-Multi) | Upstream calculation references Cboe quote downloads; code license != market-data rights | Existing licensed-source-aware gamma and current `v11_gate.py` |
| [0DTE Dealer Gamma](https://github.com/puneet-chandna/0DTE-dealer-gamma) | **PolyForm Noncommercial**, not OSI open source; commercial reuse prohibited without separate permission | Observe public mathematical concepts only, implement none of its restricted code |
| [finvizfinance](https://github.com/lit26/finvizfinance) | MIT code but scraping/redistribution conditions for Finviz source separate | Keep `source_permissions.py` closed absent provider license |
| [yfinance](https://github.com/ranaroussi/yfinance) / [yahooquery](https://github.com/dpguthrie/yahooquery) | **One Yahoo origin**; same-origin sources don't give quorum; automated use requires prior provider authorization | Existing gate remains closed unless explicitly licensed |
| [OpenTerminal](https://github.com/ErTasselli/OpenTerminal) | Its own public feeds are for personal/educational use; code does not grant commercial or redistribution rights | Reuse conceptual layout only; existing web Terminal is lightweight |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) / [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | LLM endpoint, data rights, inference cost and nondeterminism may be non-free | Integrate only local verifiable deterministic research after model/data review |
| [LEAN](https://github.com/QuantConnect/Lean), [VectorBT](https://github.com/polakowo/vectorbt) | Large alternate backtesting engines; adding either duplicates existing engine and historical data licenses | Future optional offline experiment, not production feed |
| [Pandas TA Classic](https://github.com/xgboosted/pandas-ta-classic) / [Lightweight Charts](https://github.com/tradingview/lightweight-charts) | Already used in stock shadow and browser chart respectively | Keep pinned dependencies and test already-shipped functionality |

### Adoption-status semantics

- **Function present**: code and UI hooks exist; they do not prove current valid market data.
- **Concept implemented independently**: our own Python formulas, not a fork/submodule/vendor copy.
- **Reference**: original repository verified but **not** installed or connected.
- **Review**: repo known but specific license/update/data terms need more validation.
- **Blocked**: known copyright, commercial-use or provider-automation issue.
- **Ambiguous**: name alone does not uniquely identify a particular repository, so link deliberately absent.

**Runtime evidence is separate from CI**. Merge and Vercel `READY` prove code delivery; inspect durable bot-state for real current candles and Telegram receipt before claiming that data or live alerts work. Adding 50 dependencies would increase security and maintenance risk with no guarantee of new lawful data. 
