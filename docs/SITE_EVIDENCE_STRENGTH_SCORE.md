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

## What the number is, and is not (2026-10-28)

**What it is:**
- An **engineering rating of evidence completeness**: how much of the evidence the rubric asks for is present and recent.
- Fixed weights, recomputed by `GHAZI Evidence Strength Score` from published files. It changes only when those files change.

**What it is not:**
- It is uncalibrated. It is **not** confidence in a recommendation, a win rate, accuracy or measured performance.
- The site labels it «اكتمال الأدلة (تقييم هندسي)» ("evidence completeness (engineering rating)").

The five questions it is often confused with, kept apart:

| Question | Covered by this score? | Where it is answered |
|---|---|---|
| Did the runs succeed (run health)? | No. `feed_operations` measures publication recency, not job success | Workflow runs; status taxonomy on the site |
| Is there data for the use (coverage)? | Partly: charts, prices, filings, options components | `source_rights.json`, analysis funnel in `daily_plan.json` |
| Is the data fresh? | Partly: 48h/72h windows inside components | Each file's own `generated_at` / source times |
| Was the analysis computed (completeness)? | No | `daily_plan.json` `analysis_funnel` (known → news → bars → analysed → qualified) |
| How did it perform (measured performance)? | **No.** `walk_forward` counts research sample coverage only | `trading-readiness.html`: matured outcomes only, with their sample sizes |

### History: 48 → 19 → 14 (from bot-state `runtime/public/data/site_strength.json`)

| From (UTC) | Score | charts | prices | filings | options | walk-forward | freshness | What changed |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-10-19 09:51 | 41 | 25 | 0 | 0 | 0 | 6.28 | 10 | first version |
| 2026-10-19 12:05 | 46 | 25 | 0 | 0 | 5 | 6.28 | 10 | historical OCC OI became valid |
| 2026-10-19 17:26 | **48** | 25 | 0 | 0 | 5 | 7.68 | 10 | more research samples |
| 2026-10-20 11:31 | 19 | 0 | 0 | 0 | 5 | 8 | 6 | two minutes after #325 (automated Yahoo/Nasdaq.com access stopped, 11:29 UTC): no source-dated chart report any more |
| 2026-10-21 00:44 | **14** | 0 | 0 | 0 | 0 | 8 | 6 | two minutes after #336 (OCC gated per its terms, 00:42 UTC): no valid OCC OI any more |

- The drop follows the rubric's original conditions: the evidence it rewards stopped being produced, for rights reasons.
- The weights were not changed, and the number will rise only when those conditions are met again. Example: a licensed, source-dated chart report restores the 25 chart points.

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
