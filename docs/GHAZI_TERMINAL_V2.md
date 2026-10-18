# GHAZI RADAR terminal v2 — one source of market truth

New homepage categories:
1. Indexes SPX, NDX, DJI, RUT, VIX, ETFs: daily technicals and completed session date.
2. Established large-cap watchlist, with actual scanner rows only when present.
3. Volatile/growth watchlist. Inclusion is NOT proof a company is currently small-cap.
4. News desk: verified SEC links separate from Google RSS headlines and press research.
5. Actual OHLC candles, EMA20/50, RSI14, ATR14, and last completed session levels.
6. All older Omega advanced tools remain accessible behind a separate panel.

The market chart uses the existing TradingView Lightweight Charts CDN, with a
built-in SVG OHLC fallback if unavailable. No missing candle is fabricated.
Only validated published OHLC data is used: bot-state index_charts.json from
the SAME index-radar workflow, plus at most six existing daily scanner charts.
No duplicate Yahoo index fetch/scheduler, no paid account and no OPRA claims.

Daily bars exclude today's unfinished session until NY 16:30. Intraday
5m/15m bars are only used after their full bar lengths have passed.
News, quotes and options differ in evidentiary authority. Scores are not
win probabilities, and missing feeds and stale series are explicitly shown.

Published site: https://ghazir.vercel.app