# GHAZI RADAR — Engineering Integration Audit (2026-10-21)

This is an engineering audit of the **actual** GHAZIBOT `main` at review time, not proof of authorization to redistribute provider data or a record of production deployment. Status vocabulary: **existing**, **new PR**, **gap**, **not production verified**. No upstream files copied.

## Ten mandatory upstream projects: source / license / data / feasibility / measurable function

| Project and verified repository | Upstream source-code value | License / incorporation | Data prerequisite | Existing GHAZIBOT capability | New functional integration or concrete gap | Output/evidence |
| --- | --- | --- | --- | --- | --- | --- |
| [OpenTerminal](https://github.com/JamievanRiel/openterminal) | Provider routing, cached panels, watchlists, market movers, extensible workspace, UX fallback | MIT; do not embed Electron in Vercel | Different feeds require individual permitted use | Public index/dashboard, terminal panels, custom watch and options cards | **PR #349** gives togglable web chart layers; remaining workspace, heatmap/mover improvements are gaps | [chart tab](https://ghazibot.vercel.app/#tab-chart) (may not be live until deployment); no Electron code vendored |
| [Qullamaggie Breakout Scanner](https://github.com/VladPetrariu/Qullamaggie-breakout-scanner) | Factor ranking, ATR compression, relative strength, multi-timeframe level validation | MIT | Original uses yfinance; no implied automation entitlement | `breakout_pressure.py`, relative strength/EMA, breakout setup V3 shadow | **PR #349** adds preceding-20-completed-bar breakout/breakdown levels; no additional provider calls | Chart research layer; requires source-valid OHLC |
| [GammaGrid](https://github.com/gammagrid/gammagrid) | IV surfaces, historical OI snapshots, gamma changes, watchlists and strike heatmaps | **AGPL-3.0**; never copy core code into proprietary platform without obligations | Yahoo chain data in original; cannot take hosted app account as a data resale license | `free_gamma_engine.py` call/put wall, signed GEX proxy, heuristic flip; `gammagrid_research.py` manual-only bridge | **PR #350 rebased** independent strike heatmap in `gamma_maps[symbol].heatmap_research`, strict provenance and display disabled; IV surface and dated OI-history are still gaps | Options JSON **research only**, not public/Telegram, not executed |
| [GEX Analytics](https://github.com/pikki622/gex-analytics) | 1%-shock or 10bp spot gamma profile visualization | MIT | Upstream uses Cboe data; no unauthorized endpoint access | `ghazi_gex_multi.py` has SPX gamma profiles, model Greeks and source controls | **Rebased gamma PR** adds bounded strength/strike display data independent of Cboe | In options payload only; not execution grade |
| [Options Volume Scanner](https://github.com/KPH3802/options-volume-scanner) | Per-contract anomaly against historical baseline, weekday/expiry normalizing | README claims MIT, root LICENSE absent at review; **do not copy without confirmed grants** | Need historical daily contract volume from authorized provider | `option_anomaly.py`, `free_contract_volume_store.py` with observed last-trade timestamps | Weekday/expiry cohort stratification still to be evaluated; upstream itself reports insignificant historical predictive results | No new alert/return claims |
| [Insider Detector](https://github.com/mlaina/insider-detector) | CALL concentration, OTM, notional and DTE context; label safer as unusual flow | README claims MIT, root LICENSE absent at review; no code copying | Valid contract chain, current/previous OI, licensing | `flow_analyzer.py`, independent option score, Vol/OI and DTE quality gates | Clustering/context rubric is an enhancement candidate, not proof of insider trading | No production claim |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | Provider adapters and normalized queries with provenance | Current README states Apache-2.0 for Open Data Platform; pin release/version and inspect specific modules | Each API provider retains separate terms and restrictions | `data_fabric.py`, provider metadata, `source_permissions.py` | Adapter parity/source health work recommended rather than embedding the whole platform | No new source connected in this PR |
| [Pandas TA Classic](https://github.com/xgboosted/pandas-ta-classic) | 200+ technical studies and candlestick patterns | MIT, attribution upon copying | Authorized completed OHLCV | `pandas_ta_bollinger_shadow.py` already running in stock-watch workflow (0.8.32); other indicators exist internally | Avoid redundant library installation; benchmark chosen patterns before promoting | Existing research shadow, not new source |
| [EdgarTools](https://github.com/dgunning/edgartools) | SEC structured forms, Form 4, corporate issuances, 10-Q/K | MIT | SEC fair access with valid identity and authorized API use | `edgartools_research_adapter.py`, SEC access health / dilution engines | Extend filing parser and retry only if source access works; SEC HTTP 403 not bypassed | Existing adapter; no new live SEC call |
| [Lightweight Charts](https://github.com/tradingview/lightweight-charts) | Fast HTML5 candlesticks and price levels | Apache-2.0 and attribution | Authorized OHLC publication | `public/market-chart.js` already renders OHLC and planning levels | **PR #349** completed-bar technical overlays, user-selected toggles, invalid OHLC rejection, optional T3 | [chart tab](https://ghazibot.vercel.app/#tab-chart); Node regression + GitHub CI |

### Ambiguous project labels — no false identities

These are **search terms, not sufficiently specific repository identities**:
`Anomaly Radar`, `StockScreener`, `Options Flow Scanner`,
`Unusual Options Activity`, `Institutional Volume Analysis`,
`Liquidity Heatmaps`, `Market Breadth`, `Sector Rotation`,
`SEC Catalyst Detection`.

GitHub repository search surfaced possible examples:
- [hackingthemarkets/stockscreener](https://github.com/hackingthemarkets/stockscreener) under StockScreener.
- [Buzzfund/UnusualOptions](https://github.com/Buzzfund/UnusualOptions) under Unusual Options Activity.
- [bankrollhunter/market-breadth](https://github.com/bankrollhunter/market-breadth) under Market Breadth.
- [KirkHadley/SectorRotation](https://github.com/KirkHadley/SectorRotation) under Sector Rotation.
- [tubakhxn/Liquidity-Heatmap-Order-Book](https://github.com/tubakhxn/Liquidity-Heatmap-Order-Book) under Liquidity Heatmap.

These are **unapproved candidates**, not necessarily the upstream the user meant; no copied code, claims of vendor rights, or claimed integration. Each requires separate code, version, license and data review.

## GammaGrid vs current GHAZI: independent engineering assessment

- Already present: by-strike signed GEX proxies, call/put walls, heuristic `gamma_flip`, options contract sorting, gamma/OI coverage. `ghazi_gex_multi.py` also supports modeled spot-sweep profiles for SPX.
- Added in gamma PR: bounded heatmap rows with signed-intensity %, strike OI and coverage flags, **without copying AGPL code**; false output on missing/malformed exposure, not fabricated 0.
- Still missing: **IV term-by-strike surface**, time-series **true provider-dated OI change**, authorized ongoing options-flow ingest, client-side gamma heatmap/contract sorting. These require provider rights and reliable input timestamps.
- `gamma_flip` calculated by cumulative signed exposure across strike is **not the same** as a modeled sign-change across hypothetical underlying price; they must remain separately labeled and never be substituted.
- GEX signs use **assumed** call-positive/put-negative convention. Aggregate OI cannot identify actual dealer holdings. No claims of dealer hedging action without counterparties.
- Levels and signed intensity are **model research**, not probabilistic forecasts, executable quotes, or implied call/put purchase advice.

## Integration log and acceptance

| PR | PROJECT → FUNCTION | Tests | Site / bot visibility | Production evidence |
| --- | --- | --- | --- | --- |
| [#349](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/pull/349) | Lightweight Charts / Qullamaggie idea / OpenTerminal UX → EMA 20/50, previous-20 support and resistance, research breakout levels, toggle toolbar and input guards | GitHub Actions green before merge | `public/market-chart.js` under Chart tab; only source data already published | **Check deployment and real selected chart separately; CI is not production** |
| [#350](https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/pull/350) (superseded by rebased PR) | GammaGrid/GEX concepts → by-strike independent heatmap, no AGPL copy | Original CI green, rebase retested separately | `options_latest.json -> gamma_maps[symbol].heatmap_research`; `display_authorized=false` | **Not authorized for public distribution; no runtime verification yet** |

**Data tiers:** IMPLEMENTED = code/CI; DATA-CONNECTED = authorized source supplied with valid data timestamps; PRODUCTION-VERIFIED = observed real runtime and user-visible output. The latter two are not satisfied just because a source schema or test fixture exists.

Do not weaken `v11_gate.py`, source-family quorum, deduplication, or Telegram WATCH vs CONFIRMED meaning. Source-policy blocks must stay effective. Do not create a new competing bot-state writer.
