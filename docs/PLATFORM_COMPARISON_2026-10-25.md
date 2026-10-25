# Platform comparison and what GHAZI applied — 2026-10-25

Basis: the platforms' public product pages and documented features. We did not test accounts or paid tiers,
so feature availability per tier is not claimed. Data rights decide what GHAZI can copy. A feature that needs
price data stays blocked until a permitted price source exists (`docs/PRICE_SOURCE_INVESTIGATION_2026-10-25.md`).

| Platform | Core idea worth learning | GHAZI status | Blocked by |
|---|---|---|---|
| Finviz | Screener with filters (cap, price, float, volume, sector), heat map, news per ticker | Partial: the catalyst watchlist ranks official events. Size comes only from SEC public float (#380), otherwise «الحجم السوقي غير متحقق» ("market cap unverified"). | Price, volume and float filters need a permitted price source. No market-cap heat map. |
| TradingView (widgets) | Charts and technical-rating widgets in the visitor's browser | APPLIED: index and stock widgets. They are labeled as TradingView's computation, not GHAZI's. | Non-display use is prohibited, so GHAZI computes nothing from them. |
| TrendSpider | Multi-timeframe analysis, automated trendlines, market-insight sheet | APPLIED in part: pre-open daily sheet (#381) with XNYS calendar, NY/Riyadh times, catalysts and rate backdrop. The multi-timeframe engine is coded (`options_radar/daily_plan.py`). | Frames W/D/4H/1H/15m/5m need bars; owner-private only, with an Alpaca key plus authorization. |
| Barchart (options) | Unusual activity, IV rank, options flow tables | Partial: the options pages show research gates (V11), the model-GEX caveat and the quality of free sources. | No licensed OPRA quote; Cboe auto-extraction prohibited. |
| Koyfin | Macro dashboards (yield curve, positioning), clean data provenance | APPLIED: Treasury curve plus CFTC TFF positioning (#377/#379), with structural breaks dated when knowable, not in hindsight. Data Hub shows source, time and licence per dataset. | — |
| StockAnalysis | Company page: filings, fundamentals, events in plain language | Partial: SEC filing topics (8-K items, S-4/425, 13D) and FDA/ClinicalTrials events per company (#375). | SEC requests are refused until `SEC_USER_AGENT` is set (HTTP 403 "Undeclared Automated Tool"). |
| OptionStrat | Payoff diagram of a CALL/PUT at expiry | APPLIED earlier: theoretical payoff chart (aria «الرسم النظري للربح والخسارة…»). | Live premiums need a licensed quote. |

## Applied in this round (Arabic UX)

- Five separate states per engine on the trust panel (PR #382). A green run is no longer shown as a working engine:
  run / source / data / analysis / alert.
- The daily plan sheet in the "pre-open" panel (#381): it says plainly that public prices are unavailable and why.
- The four workspaces remain (indices / large / small and speculative / options) as organized in #374.

## Not copied

No code was copied from these platforms; all are proprietary. Ideas only.
