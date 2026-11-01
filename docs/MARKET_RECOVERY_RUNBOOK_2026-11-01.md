# GHAZI RADAR — 2026-11-01 market-feed recovery and proof of acceptance

## What was actually broken

The last published `runtime/public/data/data-status.json` (2026-10-31) had zero active stock and options feeds and two critical pipeline errors. The `daily_plan.json` counted **zero fetched / analysed symbols** and private analysis was blocked by unrecorded Alpaca source-use authorization. The SEC EFTS fetch returned HTTP 403. The walk-forward gate did not pass and there were no eligible executed option samples.

A green GitHub Actions run, a READY Vercel deployment or an ops Telegram receipt **is not a trading-data success**. The project must not describe any of those as accurate CALL/PUT signals.

## Automated, inspected recovery acceptance

The single existing `site-evidence-strength.yml` publisher now creates
`bot-state/runtime/public/data/market_acceptance.json` from the **actual**
daily-plan, market-operations, scorecard and trading-readiness reports.
The report separates:

- `private_bars_observed`: actual owner-private Alpaca bars were fetched.
- `private_multi_frame_levels_computed`: those bars produced a nonempty measured plan with complete frames.
- `private_market_report_telegram_accepted`: the real private plan delivery path reported `DELIVERED`.
- `operational_telegram_digest_accepted`: routine ops Telegram delivery only, **not** a market signal.
- `out_of_sample_trading_edge_proven`: mature walk-forward and independent performance validation.
- `execution_grade_option_quotes_verified`: execution-grade contract quotes, independent of research.

All checks fail closed when evidence is missing, stale or inconsistent.
Only aggregate counts, statuses and actionable *IDs* appear on the public
site/state. Private prices, candidate symbols, account details, credentials,
raw quotes and derived owner-private levels never leave the runner.
The readiness JSON is research-only and never authorizes broker execution.

## Minimal owner actions for legitimate free private analysis

1. Create a free **Alpaca Trading API** account (personal owner use). Official documentation: https://docs.alpaca.markets/us/docs/about-market-data-api.
2. In GitHub for `GHAZMOTIEBIPRO/GHAZIBOT` → **Settings → Secrets and variables → Actions → Secrets**, add `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`. Never paste the keys into a chat, public issue or repository file.
3. Read Alpaca's applicable agreements first. **Only if the owner's private computational use is permitted**, create Actions variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`. This is a record of review, **not** an independent grant of exchange redistribution rights.
4. For a private owner-only Telegram report, configure the owner's Telegram destination via `TELEGRAM_OWNER_CHAT_ID` secret or the existing username-verified private chat. After permission review set `ALPACA_PRIVATE_ALERTS_AUTHORIZED=true`. The bot validates destination type on every delivery and never sends these prices to a group/channel.
5. Verify **GHAZI Settings Check**, then **GHAZI Private Market Scan** and **GHAZI RADAR Daily Plan**. Observe `market_acceptance.json`: actual bar counts, computed frames and receipt status must change from `false` only when independently proved. Credentials or job success alone cannot change them.
6. Optionally restore official SEC submissions with a real named `SEC_USER_AGENT` (name and contact email) provided as a secret. An HTTP 403 on GitHub's shared runner may still block access; never disguise refusals as fresh filings.

### What the free account cannot achieve

Alpaca Basic provides IEX partial-venue real-time equity coverage and *historical* SIP data delayed by at least 15 minutes; free options quotes are indicative, not execution-grade OPRA. A 15+-minute delayed chart may support private research, but not a precise immediate entry for 0DTE SPX options. SPY cannot substitute for SPX and QQQ cannot substitute for NDX in a contract quote. Sources like Twelve Data Basic carry their own internal/non-display conditions and cannot automatically be redistributed to public Telegram or a website.

**Release rule:** source → actual valid completed bars → levels → private research report accepted → independently measured out-of-sample results. Every stage must have independently inspectable evidence. Zero stages may be skipped by raising a confidence score or adding a GitHub project.
