# Reference sites review (UX only) — 2026-10-28

**Evidence:** workflow `reference-review.yml`, run 40763275959 (job 123080561978), 2026-10-28 20:26–20:29 UTC.
- The workflow opened each public home page once with Playwright, on a desktop viewport and a phone viewport, after checking the site's `robots.txt` for `*`.
- It recorded only structure: title, lang/dir, navigation labels, headings, element counts, sticky/bottom bars, font, base colours and page height.
- Nothing was stored, logged in, scraped beyond the landing page or republished.
- No logo, text or design was copied. Ideas below are re-implemented in our own words and code.

**Verification level:**
- Structure was observed automatically.
- Features behind log-ins or paywalls were **not** seen.
- Interpretation of "user need" is ours, not the site's claim.

## What each site showed (observed) and what we take

| Site | Observed (runner) | User need | Our implementation | Data need | Kind |
|---|---|---|---|---|---|
| OX CHART (oxchart.sa) | ar/rtl; phone **bottom bar of 5** (الرئيسية / التحليل / الأوبشن / جاما / المزيد, 60px); sections «الأبرز اليوم», «مزاج السوق», «أجندة الأسبوع», heatmap; Readex Pro 16px; dark bg | One-thumb navigation; a day's highlights first | Bottom nav of 5 sections, 60px + safe area (U5, coded). Week agenda: **not built in this change** (needs a dated-upcoming-events field we don't publish yet) | Own event dates (FDA, trials, Federal Register) | UX |
| mrchart.com | HTTP 403, Cloudflare "security verification" | — | Not reviewed; we did not try to bypass the check | — | — |
| Mr WallStreet | ar/rtl; course/subscription marketing; Tajawal 15px | — | Nothing product-related to learn from the landing page | — | — |
| ChartXpert Options Desk | Arabic headings, IBM Plex Sans 16px; sections «تحليلات لا توصيات», «مسرد الأوبشن», FAQ on gamma flip | Know what the tool is and isn't; learn terms | Glossary in «المزيد» (11 terms); «ليست توصية» note on radar rows | None | UX |
| obitrade2030 | ar/rtl blog; "four editorial standards": source accuracy, realistic examples, precise Arabic terms, continuous updates | Trust in explanations | Each row shows source + time; methodology links in «المزيد» | None | UX |
| Finviz | 27 tables, heatmap canvas, dense screener | Scan many symbols fast | Lists stay compact; filter/sort per tab (existing) | Licensed quotes for a full screener (not held) | UX / data |
| OptionStrat | 40 named strategies; "options profit calculator" | Know break-even and max loss before deciding | Single-leg option at expiry already existed (options tab). **Added in this change:** position size from the user's own risk (capital, risk %, entry, stop, optional target → shares, loss at stop, R multiple) in «المزيد» | None (user inputs only) | UX |
| Unusual Whales | flow, dark pool, congressional trading, market-maker exposure | Large-trade context | Not built: needs licensed trade/flow data; we do not infer flow | Licensed OPRA/trade prints | API-data |
| SpotGamma | key daily levels, "report card", free SPX gamma page | Levels plus a public track record | Track record only from our own matured outcomes (existing reliability page); no levels without data | Licensed options chain | API-data |
| Market Chameleon | "Access Denied" | — | Not reviewed | — | — |
| Barchart options | IV rank/percentile, put/call ratio, unusual activity, calculator | Volatility context | Not built without a licensed chain; calculator covered above | Licensed options chain | API-data |
| Stock Analysis | H1 "Search for a stock to start your analysis"; watchlist; IPO lists | Search first | Search in the top bar on every section (existing); watchlist section (U5) | Nasdaq Trader directory (held) | UX |
| TradingView widget docs | Official embeddable widgets (charts, tickers, screeners, calendars) | Charts without holding quotes | Already embedded: tape, mini/advanced chart; theme follows the saved theme (U5) | TradingView's own data, shown as theirs | Embed |
| Koyfin | Little exposed before log-in | — | — | — | — |
| TrendSpider | marketing: backtesting, scanners, AI assistant | — | No change; we don't claim AI predictions | — | — |
| Smart Income Flow | ar/rtl; phone bottom bar of 6 (الرئيسية / الفرص / حلل سهمك / زخم العقود / محفظتي / حاسبة الصفقات); «النتائج», «كيف تعمل؟» | Calculator and results in reach | Calculator in «المزيد»; results only from our measured outcomes | None for the calculator | UX |

## Not taken, and why
- **"Whale" or flow labels:** we have no trade prints (AGENTS.md data rule 6).
- **Gamma walls as support/resistance:** model levels need a licensed chain, and even then they are estimates (ghazi-gamma-options).
- **Paid-tier screens:** not observed and not needed.
