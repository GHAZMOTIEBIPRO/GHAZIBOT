# GHAZI RADAR — trusted free-data provider activation (2026-10-31)

## Implemented and tested
- New `scripts/verify_free_market_sources.py`: account-isolated *read-only* official API health checks for Twelve Data Basic, Alpaca (IEX + **indicative** options), Tradier sandbox/personal brokerage and SEC EDGAR official submissions.
- Runs under the existing **GHAZI Settings Check** workflow, including on approved main pushes and once each US-weekday trading session. No provider secret is logged, published, uploaded as artifact, added to Git history, or sent to a shared Telegram destination.
- In the existing **GHAZI Private Market Scan** workflow, a new `twelve-non-display` job is completely independent of the Alpaca job guard. It uses Twelve Data 5-minute bars for `SPY,QQQ,TSLA,AMD,MU,NVDA,MSFT,BABA,GOOG,GOOGL,META`, runs the existing tested S/R and ORB computations privately and logs **health counts only**.
- Requests are throttled to one symbol every 12 seconds, with at most 11 Twelve Data credits/run; at three regular weekdays sessions this is up to **33 credits/day** for the new Twelve Data job. **Other** Twelve Data jobs can also consume credits; never infer that this budget protects a shared account from all other jobs. Provider quota/429 stops the scan; source failure never creates a trade signal.
- SEC uses the official `data.sec.gov/submissions/CIK0000320193.json` API only with a valid named contact User-Agent; SEC's Fair Access rate limit is 10 total requests/sec per user (our probe is one call).
- Tradier uses a validated sandbox or brokerage hostname, never a user-supplied arbitrary URL; sandbox prices are **15m delayed, no Greeks**. Personal-use API terms apply; a production brokerage token is separate from a sandbox token.
- Alpaca Basic IEX is single-venue, not SIP; option snapshots are **indicative, not executable OPRA**. The prior GHAZI CORE Ω engine remains owner-private and gated.
- Massive.com or MarketData.app market data are not enabled as public bot feeds. A ChatGPT connected data account is **not** a GitHub Actions API secret and does not confer redistribution permissions.

## Configuration (only owner, after reviewing provider agreements)
GitHub repository → Settings → Secrets and variables → Actions.

For the API-availability / research check:
| Provider | Secrets | Variables / consent | Output |
|---|---|---|---|
| Twelve Data Basic | `TWELVE_DATA_API_KEY` | `TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED=true`, and `DATA_TERMS_CONFIRMED` includes `twelve_data` | Private non-display 11-symbol level computation; no prices or derived levels in Telegram/site |
| Alpaca | `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` | `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`, and `DATA_TERMS_CONFIRMED` includes `alpaca` | Private IEX and indicative option source quality; separate private option scanner if authorized |
| Tradier | `TRADIER_TOKEN` | `TRADIER_INTERNAL_DATA_USE_AUTHORIZED=true`, `DATA_TERMS_CONFIRMED` includes `tradier`; optionally `TRADIER_BASE_URL=https://sandbox.tradier.com` | Personal API sandbox quote and expiry source check |
| SEC EDGAR | `SEC_USER_AGENT` | Official name plus real contact email | SEC public filings identity check |

`DATA_TERMS_CONFIRMED` is one comma-separated string, e.g. `twelve_data,alpaca,tradier`. Never set it merely to make a test green; it records the owner's actual review of each provider's terms.

If no keys exist, the job still runs and prints `NO_KEY` per provider. If terms are not confirmed, prints `OWNER_TERMS_NOT_CONFIRMED` **without sending any request**.

## Why this does not authorize option trades
1. The Twelve Data Basic licence is **internal non-display**. It is not a website/Telegram quote publishing licence.
2. The Tradier sandbox data are delayed 15 minutes, and the sandbox does not provide provider Greeks.
3. Neither data availability nor a correct 5m price bar proves actual execution at the displayed option bid/ask.
4. `SPX` / `NDX` cash-index prices and index-option roots are not the same data product as ETF `SPY` / `QQQ`.
5. No automatic orders or V11 bypass. Private analysis may produce a research scenario, but real option alerts still need allowed execution-grade quotes, proper contract volume/OI and out-of-sample validation.

## Official sources
- Twelve Data Basic limits and rights: https://twelvedata.com/pricing ; https://twelvedata.com/terms ; https://support.twelvedata.com/en/articles/5615854-credits
- Tradier market data/sandbox: https://docs.tradier.com/docs/market-data ; https://docs.tradier.com/overview/faq
- Alpaca market data and options entitlement: https://docs.alpaca.markets/us/docs/about-market-data-api
- SEC Developer and Fair Access: https://www.sec.gov/about/developer-resources ; https://data.sec.gov/

## Acceptance
`pytest -q tests/test_verify_free_market_sources.py tests/test_twelve_non_display_scan.py tests/test_private_acceptance.py tests/test_twelve_data_budget.py tests/test_check_settings.py`

The entire repository test suite must pass before merging.
