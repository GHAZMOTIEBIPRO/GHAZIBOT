# BLACK BOX — External Audit Evidence

**Audit retrieval window:** 2026-09-29 around 18:00 UTC
**Repository:** https://github.com/GHAZMOTIEBIPRO/GHAZIBOT
**Observed production dashboard:** https://ghazibot.vercel.app

> This is an evidence log, not a claim that every production capability is healthy. Times and conclusions below are limited to the linked external records.

## Production endpoint observations

| Endpoint | Observation | Source |
|---|---|---|
| Health | HTTP 200 with `status: degraded`; payload `generated_at: 2026-08-17T21:50:02Z`; `option_quotes_production_ready: false`; `option_flow_production_ready: false`. | https://ghazibot.vercel.app/health |
| Data status | HTTP 200 with `status: degraded`; `option_provider_readiness: FALLBACK_ONLY`, with Yahoo/YFinance-only chains and no production option quotes/flow. The embedded payload also records historical SEC EFTS 403 status. | https://ghazibot.vercel.app/data-status |
| Deployment | Latest GitHub production deployment at retrieval time reported `success` for commit `42ab7e64e94514e49cd3d3ab4818f136c4e03422`; deployment URL below. | https://ghazibot-j29zk8845-ghazis-projects-696f16f5.vercel.app |

## GitHub Actions evidence

| Capability | External record | Evidence observed |
|---|---|---|
| Latest fast stock discovery | https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36584783984 | Successful scheduled run, started `2026-09-29T14:43:20Z`. Downloaded artifact carried a fast-market snapshot generated at `2026-09-29T14:46:12Z`. |
| Latest stock radar | https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36585164299 | Successful workflow-run, finished `2026-09-29T14:47:03Z`. Downloaded artifact `stocks_latest.json` had six actionable/deep-validated stocks, zero errors, and a `HEALTHY` stock-path result; official primary causes were zero. |
| Latest options radar listed at retrieval | https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36502889368 | Reported success but was created at `2026-09-29T00:23:49Z`; it must not be treated as current-session production option evidence without its artifact and freshness validation. |
| Documented options failure | https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36169971081 | Failed run logs showed unconfigured Tradier, MarketData.app, and Finnhub keys; empty Yahoo responses for several symbols; and SEC 403 responses. |
| Telegram keeper | https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/36311156711 | Successful run; Telegram identity verification and destination sealing succeeded, while the `Destination not ready status` branch was skipped. This is positive connectivity evidence from 2026-09-27, not proof of a current message delivery. |

## Access limitations

- The audit token could enumerate workflow names/runs but received HTTP 403 when listing GitHub Actions secret names or variables. Their existence and current values are therefore **unverified**.
- No Telegram token, chat ID, or market-data provider key is present in the current local sandbox environment. No live Telegram send was attempted.
- GitHub Actions schedule activation was visible, but a workflow being marked successful does not prove fresh market data, option-chain readiness, or message delivery.
