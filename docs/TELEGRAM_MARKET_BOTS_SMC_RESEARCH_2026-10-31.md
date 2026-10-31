# GHAZI RADAR — Telegram bots / market-structure OSS selection and implementation
Date: **2026-10-31**. Examined live GitHub repository metadata, README, official upstream APIs and existing GHAZI code.

## Decision
**Do not replace GHAZI RADAR with another Telegram trading bot.** Extract narrowly defined, testable components from selected permissively licensed projects. Borrow ideas, not market-data access rights, fabricated win rates, or third-party credentials. The target is US index proxies SPY/QQQ and mega-cap equities; SPX/SPXW cash-settled index options are a different product.

### Independent review of relevant repositories
| GitHub project | Verified licence / maintenance | US market fit / documented capability | Adoption |
|---|---|---|---|
| [SnowIlia/ai-stock-market-analyzer](https://github.com/SnowIlia/ai-stock-market-analyzer) | MIT; code present and updated Sept 2026; 0 stars at review | SPY-focused Telegram report, options context, multi-model opinions, prediction validation | Borrow structured *analysis vs counter-thesis vs source health vs validation* report; do not import Yahoo options data or claimed AI probability |
| [kayasolomon/poi-liquidity-detector](https://github.com/kayasolomon/poi-liquidity-detector) | MIT, TypeScript, 0 stars | Non-repainting equal highs/lows, closed-bar sweep → CHoCH, detection-time prefix tests | **HIGH**: independent Python closed-bar prototype below; preserve event-known-at bar evidence |
| [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) | MIT; 2,127 stars | FVG, swing, BOS/CHOCH and order blocks; confirmed swing requires future bars | Already integrated in `options_radar/open_source_research.py` with confirmation lag; do not duplicate |
| [Khaymat/pyvsmc](https://github.com/Khaymat/pyvsmc) | MIT, NumPy/Polars, 1 star; Aug 2026 | High-performance FVG/BOS/CHoCH/sweep library; 92 tests claimed by author | Shadow benchmark later after independent prefix/replay confirmation; not a direct quote feed |
| [zrack/gex-terminal](https://github.com/zrack/gex-terminal) | MIT, 26 stars, Oct 2026 | Offline replayable sensitivity tests on GEX model assumptions and source health | **HIGH** for gamma sensitivity test design, not source of live dealer gamma |
| [Darthreign/gex-dashboard](https://github.com/Darthreign/gex-dashboard) | MIT, 19 stars, Oct 2026 | SPX/NDX GEX dashboard derived from Cboe delayed web quotes | **DO NOT FEED PRODUCTION**: code licence does not grant Cboe data extraction/publication rights |
| [dsalimov/momentum-radar](https://github.com/dsalimov/momentum-radar) | No verified SPDX licence; zero stars | RVOL, trend breaks, weighted signal registry, Telegram, cooldown, SQLite | Architecture ideas only; keep own implementation/avoid unlicensed code copying |
| [Alkyones/marketpulse-telegram-tradebot](https://github.com/Alkyones/marketpulse-telegram-tradebot) | No verified SPDX licence; zero stars | /analyze, /signal and alerts; 20-day swing S/R, ATR, RSI, MACD | Telegram UX inspiration only; source and performance not independently verified |
| [beejak/fin-assistant](https://github.com/beejak/fin-assistant) | No verified SPDX licence; zero stars | Indian-market channel scoring, signal outcome grading, watchdog and duplicate notifications | Adopt *evidence lineage / later validation* design, not India-specific data, copying or trading claims |
| [noutrexx/bist100-alert-bot](https://github.com/noutrexx/bist100-alert-bot) | MIT, zero stars | Finite conditions, cooldown, market hours, test suite | Useful lean Telegram formatting/cooldown ideas; Turkish market and Yahoo input not transplanted |
| [mahmoud20138/OrderFlow-Analysis-Pro](https://github.com/mahmoud20138/OrderFlow-Analysis-Pro) | MIT, 77 stars | Footprint/delta/absorption from Bybit and MT5 feeds | **Not US options order flow**; reuse analysis *only if* authentic U.S. tick/trade classification becomes licensed |
| [ronitg1/alpha-terminal](https://github.com/ronitg1/alpha-terminal) | GitHub API reports NOASSERTION; README says MIT, inspect LICENSE/THIRD_PARTY_NOTICES before copying | Stock patterns, options trade-level backtesting, spread/slippage, walk-forward and Telegram signals | Prioritize its **independent fill validity and backtest invariants**, not claiming realistic fills when BSM fallback is used |
| [highwatermark/momentum_agent](https://github.com/highwatermark/momentum_agent) | No verified licence; uses Unusual Whales paid inputs | Flow scores, liquidity-spread brakes, pre-trade risk controls | Architecture ideas only; never claim its Unusual Whales feed is free |
| [Fin-Chelae/FinClaw](https://github.com/Fin-Chelae/FinClaw) | MIT, 25 stars, financial agent + Telegram | Multi-LLM and multiple data domains | Not appropriate to expand current market-data surface without source governance |
| [ekkyvalent/idx-signal-bot](https://github.com/ekkyvalent/idx-signal-bot) | No verified SPDX licence; zero stars | TradingView Scanner API-based multi-ticker technical scan | Avoid reusing undocumented scanner endpoints or assuming permission to redistribute their results |

Stars are GitHub social adoption signals, **not measures of trading accuracy**. README assertions about models, backtests, or execution-quality have not been independently proven by broker fills. No third-party repo data API key, live OPRA feed, or dealer positioning becomes available merely by installing its code.

## What is already in GHAZI RADAR
- `options_radar/volume_liquidity.py` already estimates POC, VAH/VAL using **uniform intrabar OHLC volume allocation** (not exchange-executed volume-at-price), 15m same-time RVOL, VWAP, previous-day high/low sweeps and breakout volume. Avoid coding those twice.
- `options_radar/open_source_research.py` already provides `smartmoneyconcepts` with swing and FVG confirmation lag and no decision authority.
- `options_radar/core_options_strategy.py` already provides completed 5m bars, prior-high/low, OR30, EMA9/21, source-specific VWAP and indicative-only option research. It cannot verify dealer gamma / SPX executable quotes.
- Owner-only source jobs `run_twelve_non_display_scan.py` and `run_focus_options_private.py` already honor external provider account terms and produce no public derived quote levels.

## Implemented in this PR (no external dependency or extra data requests)
`options_radar/structure_liquidity_shadow.py`:
1. Only accepts validated, finished NY regular-session **5-minute** OHLCV bars, with a complete contiguous sequence.
2. A candidate swing high/low becomes usable only *after* two confirming later bars **close**; event records include `known_at_index` and `pivot_known_at_index`.
3. High sweep = wick above a **previously confirmed** swing high by an ATR-scaled minimum and close below; low sweep symmetric. It is a price-action proxy; no stop order or institutional buyer is observed.
4. A sweep followed within 12 completed bars by a close beyond the confirmed opposing swing emits `HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK` or `LOW_SWEEP_THEN_UP_STRUCTURAL_BREAK`. This is **not** dealer flow, true order-book liquidity or statistical price prediction.
5. A bar wicking both opposing pivots is explicitly `AMBIGUOUS_BOTH_SIDES_WICKED`, not assigned an invented intrabar chronology.
6. Derives 15m closes only from three consecutive completed 5m bars and labels 5m/15m trend as UP, DOWN, MIXED, or INSUFFICIENT.
7. Tests compare every event against truncated history (prefix test), incomplete/ambiguous bars, delayed future bars and owner-only Telegram research labeling.
8. The pre-existing Twelve Data private job processes these features with **no additional market-data calls** and writes only aggregate counts, not price levels or symbol-specific confidential signals.
9. The pre-existing Alpaca owner-private job includes research-only structure labels after reusing already-fetched IEX bars and its existing owner-chat access/rights gate; it does not add new Telegram sends.

## Data-maximization that remains compliant
| Source | Free relevant part | Requirement | Permitted interpretation |
|---|---|---|---|
| Twelve Data Basic | Up to **800 credits/day, 8/min** for personal internal non-display; real-time U.S. equities/ETFs | Owner account key + review of rights; no public price/derived price redistribution | 5m/15m stocks, S/R, sweep research privately |
| Alpaca Basic | IEX stock bars, indicative options where authorized | Owner credentials and per-product data rights | Single-venue stocks, delayed/indicative options **not OPRA marketable bid/ask** |
| Massive Options Basic | 2 years historical, EOD, 5 calls/min, historical minute aggregates | Provider account/key; rights restrict public reuse | Historical quoted contract research, **not live 0DTE flow** |
| SEC EDGAR | Official public 8-K/10-K/10-Q/Form 4 and company XBRL | Named User-Agent/contact; network fair-access and 403 unresolved | Company catalysts with publication + event time |
| Official issuer IR | 10 active sources at audit snapshot | Per-publisher terms, source freshness | Announcement/earnings context, not price signal |
| CFTC/Treasury | Weekly ES/NQ futures positions, US yield curve | Already operating in bot-state | Macro context, **not intraday option sweeps/GEX** |

**Never collect Telegram messages from other private bots/channels unless access and reuse are authorized.** Reposting other bot recommendations or averaging their opinions is not independent market-data confirmation.

## Operational next requirements
- Set up owner-authorized stock data accounts for a real source-backed signal demonstration. Last checked main production `NOT_TRADE_READY` with zero qualified active price/option market feeds; this PR cannot change that by itself.
- Add provider-specific quote timestamp, exchange, adjusted-contract and feed-rights metadata as observable technical evidence *per symbol*.
- To publish actual executable option CALL/PUT, require fresh two-sided marketable OPRA quotes, contract identity/expiry, quotes and market coverage, spread/depth, independent historical outcomes after costs. No proxy-based self-reported win rate.
- Before each future scoring upgrade, use fixed signal timestamp, later outcome timestamp, no look-ahead, out-of-sample walk-forward and fee-adjusted fills with attempted/rejected sample denominator. Reduce warnings, do not set confidence to a percentage without calibration.

## Official references
- https://twelvedata.com/pricing
- https://massive.com/options
- https://www.sec.gov/about/developer-resources
- https://core.telegram.org/bots/api
- Repo's own `docs/GHAZI_RADAR_ACCURACY_AUDIT_2026-10-31.md` and data permission gates.
