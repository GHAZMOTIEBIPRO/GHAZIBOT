# Free data paths by category — tested 2026-10-26

Each row was tested with one small request from a GitHub runner (probe run **40266602180**,
`scripts/probe_free_sources.py`) unless another run is named. "Wired" means a page feature now
uses it with real data; "candidate" means it passed the request test but is not used yet.
Prices and option chains are covered in `PRICE_SOURCE_INVESTIGATION_2026-10-25.md`; only what
changed is repeated here.

## 1. Symbol directory and exchanges

| Source | Data back? | Coverage / freshness | Allowed use | Key | Result |
|---|---|---|---|---|---|
| NasdaqTrader Symbol Directory (`nasdaqlisted.txt`, `otherlisted.txt`) | Files exist (HEAD 200, Last-Modified 2026-10-24 01:31 GMT, 73 KB / 150 KB). Contents **not downloaded**. | Nasdaq + other U.S. exchanges, daily | The product page (`id=symbollookup`) states Nasdaq and its licensors "retain all right, title and interest … including … the symbols"; the definitions page has no usage grant; the site copyright notice requires written consent to store or use. `id=TermsOfUse` redirects to a 404. | No | RESTRICTED by nasdaqtrader.com's **own** terms, not by Nasdaq.com's. Gate `NASDAQTRADER_AUTOMATION_APPROVED` stays closed. The probe's HEAD now also waits for the gate (the first run sent one HEAD per file before the gate was added). |
| GitHub mirrors `datasets/nasdaq-listings`, `datasets/nyse-other-listings` | Yes | Last data commits 2026-10-01 and 2026-10-24 | The datapackages name nasdaqtrader.com as the source and the READMEs defer to its copyright notice. A PDDL label on a copy cannot grant rights Nasdaq keeps. | No | **Changed:** `options_radar/github_listing_discovery.py` now follows the nasdaqtrader gate (it read these mirrors before). |
| SEC `company_tickers_exchange.json` | No: 403 "Request Rate Threshold Exceeded" | — | Public domain (SEC) | Declared User-Agent | Blocked from runners (see §3). |
| **S&P 500 members** (`datasets/s-and-p-500-companies`) | Yes: 503 rows | Name, GICS sector, sub-industry, SEC CIK, date added; data commits 2026-10-15, 10-22, 10-26 | ODC-PDDL packaging; upstream Wikipedia text CC BY-SA 4.0 (attribution kept) | No | **Wired:** `symbol-directory.yml` (single writer) → `symbol_directory.json` → search by name, leaders tab by sector, SEC EDGAR link by CIK. Current members only: not for historical tests. |

## 2. Prices and candles (changes only)

| Source | Result |
|---|---|
| OpenBB 5.0.0 (PyPI, 2026-09-29, Apache-2.0) | A wrapper, not a source. Wheels inspected: `openbb-cboe` calls `cdn.cboe.com`; `openbb-nasdaq` calls `api.nasdaq.com` / `www.nasdaq.com` / `nasdaqtrader.com`; `openbb-finra` calls FINRA; `openbb-tmx` calls TMX (Canadian, unofficial); `yfinance`, `fmp`, `polygon`, `tiingo`, `intrinio`, `alpha-vantage`, `tradier` are optional extensions for providers already in the rights matrix. No new independent free U.S. price source. |
| FRED | `fred.stlouisfed.org` timed out again from the runner (ReadTimeout). |
| Public display of prices | Unchanged: only TradingView embeds (their own data, in the visitor's browser). No price is fetched or shown by GHAZI. |

## 3. Financials and filings (SEC)

| Endpoint | Status | Kind |
|---|---|---|
| `www.sec.gov/files/company_tickers_exchange.json` | 403 | RATE_LIMITED |
| `www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` (HEAD) | 403 | HTTP_403 |
| `www.sec.gov/Archives/edgar/full-index/2026/QTR4/form.idx` (HEAD) | 403 | HTTP_403 |
| `www.sec.gov/Archives/edgar/daily-index/2026/QTR4/index.json` | 403 | IDENTITY_REFUSED |
| `data.sec.gov/submissions/CIK0000320193.json` | 403 | IDENTITY_REFUSED |
| `data.sec.gov/api/xbrl/frames/...` (HEAD) | 403 | HTTP_403 |
| `www.sec.gov/cgi-bin/browse-edgar?action=getcurrent` (Atom) | 403 | IDENTITY_REFUSED |
| `efts.sec.gov/LATEST/search-index` | 403 | IDENTITY_REFUSED |

One request each, one second apart, no retries. The probe ran with the default User-Agent
(no `SEC_USER_AGENT` secret). `edgartools` and `sec-edgar-downloader` call the same hosts and need
the same declared identity; neither is a fix for a refusal. Bulk files, indexes and incremental
daily indexes are the right design once access works (one bulk download, then daily index deltas,
cached). **Wired now without automation:** a per-company link to SEC EDGAR (the visitor opens it).

## 4. News and catalysts

| Source | Data back? | Freshness | Use | Result |
|---|---|---|---|---|
| openFDA (`api.fda.gov`) | Yes | `last_updated` 2026-10-23 | CC0 | **Wired:** news tab, leaders, small caps, stock detail |
| ClinicalTrials.gov API v2 | Yes | `dataTimestamp` 2026-10-23T09:00 | ODbL, attribution | **Wired** (administrative updates labelled "not a result" and excluded by default) |
| Federal Register API (FDA documents) | Yes | newest 2026-10-26 (priority review voucher notice) | U.S. government publication | **Candidate:** needs a sponsor→ticker review before it can name a stock |
| GDELT | In cooldown after HTTP 429 | — | Open with citation | Wired earlier; currently empty |
| FDA press RSS | No: bot-protection page (run 40238841187) | — | — | Not worked around |
| Press wires, Google News RSS | — | — | Terms forbid automated access (rights matrix) | Gated |

Event times are now kept apart in `catalyst_watchlist.json` (`events[]`): event date, the source's
own update date, and `first_seen_at` (first time our list showed it; `null` for events listed before
tracking began, never back-filled).

## 5. Economy and sectors

| Source | Result |
|---|---|
| U.S. Treasury yield curve, CFTC TFF | Working; **wired** in the market summary (10-year yield, 10y–2y spread) and index rows (asset-manager positions) |
| Treasury Fiscal Data API | 200; latest record 2026-09-30 (monthly). Candidate |
| FRED | Timeout from runners |
| Sector labels | From the S&P 500 list (wired). Sector performance needs prices → TradingView heatmap (previous page) |

## 6. Option chains

No free source permits automated collection and public display (Cboe delayed quotes: automated
extraction prohibited; Tradier: personal use; Alpaca options: indicative and private; OCC: restricted;
community GEX feeds: no licence). The options tab says this once and offers an expiry calculator that
uses no market data.

## UI libraries reviewed

| Project | Licence / activity | Decision |
|---|---|---|
| tabler/tabler | MIT; last commit 2026-10-24; Bootstrap 5 based | Not imported (would add a CSS framework on top of the existing one). Used as a reference for compact list rows, badges and empty states. |
| shadcn-ui/ui | MIT; React + Tailwind + Radix | Not adopted (needs React). Its token idea (background / card / muted / border) and sheet-on-mobile pattern are used. |
| TanStack/table | MIT; `@tanstack/table-core` 9.3.1 is framework-agnostic | Not needed yet: lists are ≤ ~150 rows with two sort keys. Candidate when a full-market table with virtual scrolling exists. |
| tradingview/lightweight-charts | Apache-2.0; 5.2.1; attribution link required | Already used on the previous page for published bars. The new page has no bars it may publish, so the chart stays the TradingView embed until a permitted bar source exists. |
