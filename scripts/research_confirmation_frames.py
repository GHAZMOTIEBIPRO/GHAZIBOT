"""Run options_radar.confirmation_study on owner-authorized Alpaca history (runner only).

Fetch: completed daily bars and 5-minute SIP bars (>= 16 minutes old) for SPY, QQQ and the owner's
leaders over the last N XNYS sessions. Output: aggregate counts/rates/R/minutes per method, overall
and per chronological half - no symbol, price, level or bar leaves the runner (log and job summary
carry statistics of the method only, the same rule as the opening-Fib replay).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals
import pandas as pd

from options_radar import confirmation_study as cs
from options_radar import daily_plan as dp
from options_radar.bar_providers import AlpacaBars
from scripts.build_daily_plan import DETAIL_INDEX_FUNDS, DETAIL_LEADERS


def sessions(now: datetime, count: int) -> list[tuple[datetime, datetime]]:
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=count * 2)).date()):str(now.date())]
    rows = [(pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for _, r in sched.iterrows()]
    return [r for r in rows if r[1] <= now - timedelta(minutes=16)][-count:]


def run(symbols: list[str], count: int, now: datetime, env, pause=time.sleep) -> dict:
    provider = AlpacaBars(env, now=now)
    status = provider.status()
    if status != "READY":
        return {"status": status}
    days = sessions(now, count + 40)  # 40 earlier sessions warm up the 1H EMA20 and ATR14
    study = days[-count:]
    signals: list[cs.Signal] = []
    halves: dict[str, list[cs.Signal]] = {"first_half": [], "second_half": []}
    coverage = {"symbols_ok": 0, "symbols_failed": 0, "sessions": len(study)}
    for symbol in symbols:
        daily = provider.bars(symbol, "1d", now - timedelta(days=(count + 80) * 2), now)
        minute = provider.bars(symbol, "5m", days[0][0], now)
        pause(0.5)
        if daily.get("status") != "OK" or minute.get("status") != "OK":
            coverage["symbols_failed"] += 1
            continue
        coverage["symbols_ok"] += 1
        drows = [{"date": b["t"].astimezone(dp_tz()).date().isoformat(), "open": b["o"], "high": b["h"],
                  "low": b["l"], "close": b["c"], "volume": b["v"]} for b in daily["bars"]]
        by_day: dict[str, list[dict]] = {}
        for b in minute["bars"]:
            by_day.setdefault(b["t"].astimezone(dp_tz()).date().isoformat(), []).append(b)
        hours_hist: list[dict] = []
        for open_at, close_at in days:
            key = open_at.astimezone(dp_tz()).date().isoformat()
            regular = [b for b in by_day.get(key, []) if open_at <= b["t"] < close_at]
            if (open_at, close_at) in study:
                past = [r for r in drows if r["date"] < key]
                atr14 = dp.atr(past[-60:]) if len(past) >= 15 else None
                weekly = dp.weekly_from_daily(past, last_closed_week_end=past[-1]["date"]) if past else []
                if past and atr14:
                    found = cs.session_signals(regular, open_at, past[-1], atr14, weekly[-1] if weekly else None,
                                               hours_hist[-60:])
                    signals.extend(found)
                    half = "first_half" if study.index((open_at, close_at)) < len(study) // 2 else "second_half"
                    halves[half].extend(found)
            hours_hist.extend(cs.bucket(regular, open_at, 60))
    return {"status": "OK", "coverage": coverage, "feed": "SIP historical (>= 16 minutes old)",
            "all": cs.summarise(signals), "first_half": cs.summarise(halves["first_half"]),
            "second_half": cs.summarise(halves["second_half"])}


def dp_tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=120)
    args = parser.parse_args()
    symbols = [*DETAIL_INDEX_FUNDS, *DETAIL_LEADERS]
    result = run(symbols, args.sessions, datetime.now(timezone.utc), os.environ)
    text = json.dumps(result, indent=1)
    print("Confirmation study (aggregate only):", text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Confirmation timeframe study (aggregate only)\n\n```json\n" + text + "\n```\n")
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
