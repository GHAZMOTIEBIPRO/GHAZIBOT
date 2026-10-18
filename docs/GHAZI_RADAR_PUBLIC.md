# GHAZI RADAR — public free research UI

The public brand is **GHAZI RADAR**. Keep the existing three research engines and their authority gates unchanged.

## Hosting and URL

- Current production Vercel project: ghazibot; canonical free domain: https://ghazibot.vercel.app/
- Public noncommercial research use only on Vercel Hobby; do not monetize on Hobby.
- The frontend remains a static site in public/. No paid infrastructure or API subscription is introduced by this change.
- The name of the HTML page does not rename the deployment or assert ownership of ghaziradar.vercel.app.

## Data-quality contract

- public/ghazi-radar-quality.js reads the persisted public data-status.json report. It looks at the bot-state runtime copy and public/main copies, selecting the newest valid provider-generated timestamp.
- A report's generated_at is **not** a market quote timestamp or last-trade timestamp. UI copy must never call it a quote time.
- No source counts or approval booleans are hardcoded. Failure or absent fields displays unknown instead of 0.
- Fallback, indicative, delayed, or unofficial chains remain research-only. Do not weaken options_radar/v11_gate.py.
- The public panel displays verified active stock/options sources, usable option chains, accepted contracts, option quote/flow readiness, reported provider family, and SEC Full-Text status.
- SEC events/financials may continue using allowed official latest-form/Submissions/Company Facts methods when the Full-Text endpoint returns HTTP 403. Never bypass website rules or scrape blocked pages.
- More records only count as better coverage after deduplication, independent provenance, permitted use, freshness validation, and quality checks.
- No unaudited third-party market data, keys, live trades, or user private portfolio data belong in public artifacts.
- Research-only UI is not a brokerage execution interface or an investment recommendation.

## Verification

Run: node --check public/ghazi-radar-quality.js
Run: node --check public/app.js
Run: pytest -q tests/test_public_ghazi_radar.py
Run applicable repository CI. Merge only after CI green and then verify the production Git-triggered deployment.
