# Evidence-based GHAZI RADAR strength score

This is a **research-data and validation readiness** metric scored 0–100,
not a trading success rate, prediction model confidence, benchmark outperformance
or live browser performance review. Each point has an explicit evidence source.
The status auto-updates on the free GitHub Actions job
`GHAZI Evidence Strength Score`, and the Arabic dashboard reads the result
from `bot-state/runtime/public/data/site_strength.json`.

## Deterministic rubric (100 points)

| Evidence category | Max | Source | Hard limitations |
|---|---:|---|---|
| Charts and timeframes | 25 | `stock_watch_charts.json` | actual research-only daily, 1h, 15m, 5m coverage, within 48h of feed publication |
| Independent price verification | 20 | `source_agreement.json` | Yahoo and yfinance same family = zero; no unlicensed cross-vendor comparisons |
| Issuer filings | 15 | `sec_filing_pulse.json` + `free_options_sources.json` | direct SEC issuer report 15; verified no-new-filings access 7; labelled third-party evidence at most 5; HTTP 403 = zero |
| Options source reliability | 15 | `free_options_sources.json` | valid **historical** OCC OI at most 5; remaining 10 reserved for independently verified entitled OPRA execution quotes |
| Out-of-sample research evidence | 15 | `state/stocks/stock_walk_forward.json` | ≤6 points for actual 60m coverage; ≤2 for independent sessions; last 7 only for ≥40 OOS samples over ≥4 sessions + passed gate |
| Publication recency | 10 | four source feed timestamps | research chart within 48h 4, source status within 48h 2, SEC report within 72h 2, other option feed within 72h 2; measures report freshness, **not endpoint availability** |

Caveats:
- A complete current research-only chart earns a **coverage** point, never a promise that the price is tradable or fresh enough for a new order.
- A successful SEC workflow returning `HTTP_403` may earn a **recent-status** point, but **zero official filing-access points**. Publishing a clear failure report is useful operational transparency.
- OOS report has no verifiable `generated_at` in the current durable state: no recency claims or predictive-accuracy percentage are made.
- UI design, responsiveness, security audit, actual Vercel availability and Telegram delivery **are not audited**. The 100 score is not an overall customer satisfaction evaluation or website accessibility assessment.
- No outside model can automatically improve a score: **ProsusAI/finbert** carries a `cc-by-nc-sa-4.0` license and QuantConnect CLI local backtests are a paid-tier feature per current product docs. Kaggle datasets are separately licensed. Do not download them into the public/commercial site without explicit authorization.
- This report uses Python standard library only, zero provider requests, zero secrets, no paid dependencies, no look-ahead outcome fabrication, and no changes to live-trade gates.

## Reproducibility

The report is generated from `bot-state` files with:

```bash
python scripts/build_site_strength.py \
  --charts stock_watch_charts.json \
  --agreement source_agreement.json \
  --sec sec_filing_pulse.json \
  --free-options free_options_sources.json \
  --walk-forward stock_walk_forward.json \
  --output site_strength.json
```

Reassess performance only after an independently verified out-of-sample
trade journal, licensed quotes and actual transaction-cost history exist.

External references: https://huggingface.co/ProsusAI/finbert ;
https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment ;
https://www.kaggle.com/docs/datasets .
