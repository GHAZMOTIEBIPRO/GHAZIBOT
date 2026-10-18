# GHAZI RADAR: autonomous stock candles, news coverage and GEX context

Stock charts:
- 16 watched symbols: 9 volatile/growth and 7 established, bounded daily and 15m
  research OHLC; selected 4 volatile symbols also have genuine 5m candles.
- Uses yfinance Yahoo source and strict bar-close/session rules. 15m/5m
  provider timestamps are bar START times, never substituted for quote time.
- Workflow stock-watch-charts.yml runs on completion of the existing index
  research job (and on its own first push). It writes ONLY stock_watch_charts.json
  in durable bot-state and has no parallel competing write paths.
- Missing chart means missing provider bars, never a fabricated candle.

News coverage:
- The existing Company News Watch owner rotates max six Google RSS issuer
  searches per execution, adding RGTI/SOFI to the watch, and hydrates the prior
  bot-state output so unchanged source-dated news remains visible for 7 days.
- Retained stories must meet the same exact issuer, URL, topic, date and
  non-authority validation as new stories. Retaining is NOT a live refresh.
- SEC may remain HTTP403, GDELT HTTP429; no hidden fallback as official.

Gamma:
- Use existing free_gex_validation.json; every GEX metric is labeled SHADOW.
- The integrated true SPX chain may be unavailable; one GEX/Flip contributor
  does not prove independent dealer gamma positioning.
- No GEX values assigned to NDX/QQQ or company-specific options; SPY sees SPX
  context only. ATR-derived +/- 1/2 volatility envelopes are explicitly
  technical SCENARIOS, not calibrated directional forecasts or gamma values.
- No execution-ready options signals or proprietary/licensed quote claims.

Updates: Existing GitHub Actions workflows, bot-state JSON and site polling;
GitHub Actions cron/workflow_run are best-effort; fully guaranteed
zero-human 24/7 uptime cannot be promised on a free plan.