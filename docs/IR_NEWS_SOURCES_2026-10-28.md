# Company news from official IR pages (non-medical) — 2026-10-28

**Probe:** `scripts/probe_ir_sources.py` (workflow `ir-probe.yml`), runs 40769985766, 40770458419 and 40770962704 (21:12–21:20 UTC).

**How it reads:**
- robots.txt is read first; an unreadable one fails closed.
- Each IR page is read once.
- Only feeds the page links to are followed, plus one level from an RSS index page.
- The log only is kept.

**Scope of each result:** a result is about that page only. It says nothing about the company's other pages, and nothing about newswires.

| Symbol | IR page | Result (run 40770962704) | Used |
|---|---|---|---|
| XOM | investor.exxonmobil.com | press-release RSS, 10 items (latest: "ExxonMobil to Release Third Quarter 2026 Financial Results") | yes (press releases) |
| NVDA | investor.nvidia.com | RSS index page → events feed (1 item: "11/17/2026 : NVIDIA 3rd Quarter FY27 Financial Results"), presentations (10), SEC filings via the IR site (20). No press-release feed listed. | yes: events, SEC filings (8-K, 10-Q/10-K, registration, proxy only) |
| AAPL, MSFT, AMZN, GOOGL, META, JPM, BA, IONQ, ASTS | their IR pages | page read; no RSS link on it | no. Platform paths are not guessed |
| BRK.B | berkshirehathaway.com | no robots.txt (HTTP 404); page read; no RSS link | no |
| AVGO, TSLA, RKLB, SOUN | their IR pages | robots.txt answered HTTP 403 to our user agent → treated as disallowed, page not read | no |

## What is published (`ir_news.json`, written only by `catalyst-watchlist.yml`)

**Facts (the company's):** headline, publication time (absolute, with zone; items without a zone are dropped), link. The link must stay on the company's site.

**Event time:**
- an events feed item that names its own date gets `event_at`;
- `source_published_at` is the listing time;
- `first_observed_at` is our fetch, with `FIRST_FETCH_OF_SOURCE` for items already present when a source was first read.

**Interpretation (ours):**
- `category` is read from the headline's words (`category_basis: HEADLINE_KEYWORDS`). A release announcing *when* results come is a schedule, not results.
- `potential_impact` is always `NEEDS_IMPACT_ASSESSMENT`.
- The summary is our own: company + category. No release text is copied.

**Failures:**
- each source fails alone and keeps its last good items with `last_success_at`;
- statuses are `ROBOTS_*`, `HTTP_*`, `FETCH_ERROR` or `NOT_XML`.

**On the site:** the items join the catalyst list as `IR_*` kinds under the news filter «أخبار الشركات (مواقعها الرسمية)» ("company news (their official sites)"). Financing that may dilute and securities registrations are flagged as risks.

**Telegram:** these kinds are not on the alert sender's allow-lists, so no Telegram message changes.

## Round 2 (2026-10-29, run 40793143955): 30 more non-medical leaders

The probe also read up to two of the IR page's own news pages for RSS links (same host, robots checked).

| Result | Companies |
|---|---|
| Press-release feed linked by the company, items with absolute times → **added** | AMD, INTC, NFLX, QCOM, KO, GD (+ GD events feed) |
| Page read, no RSS link (page or its news pages) | ORCL, CRM, MU, IBM, PLTR, UBER, PEP, WMT, COST, MA, GS, CAT, GE, F |
| robots.txt HTTP 403 → treated as disallowed, not read | TXN, HD, CVX, LMT, RTX, NOC, GM |
| Linked feed answered 403 | V |
| Only feed on a CDN host whose robots.txt disallows us | COIN |
| Linked feed address is an empty index page | BAC |

## Remaining
- Coverage is 8 of 46 probed companies (XOM, NVDA, AMD, INTC, NFLX, QCOM, KO, GD).
- The other pages need a feed they link to themselves, or a reviewed alternative; platform paths are not guessed.
- Site terms were not read per company (rights entry `company_ir_feeds`: automated access VERIFIED by robots, other rights UNKNOWN), so only headline, time and link are published.
- Any source added needs its own probe row in `data/ir_feeds.json`.
