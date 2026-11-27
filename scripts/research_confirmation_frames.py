"""Run options_radar.confirmation_study on owner-authorized Alpaca history (runner only).

Fetch: completed daily bars and regular-session 1-minute SIP bars (>= 16 minutes old) for SPY, QQQ
and the owner's leaders over the last N XNYS sessions, in 10-session chunks. Output: aggregate
counts/rates/R/minutes per rule, overall and per chronological half - no symbol, price, level or bar
leaves the runner (log and job summary carry statistics of the method only).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from options_radar import confirmation_study as cs
from options_radar import daily_plan as dp
from options_radar.bar_providers import AlpacaBars
from scripts.build_daily_plan import DETAIL_INDEX_FUNDS, DETAIL_LEADERS

NY = ZoneInfo("America/New_York")
BASELINE_SESSIONS = 10


def sessions(now: datetime, count: int) -> list[tuple[datetime, datetime]]:
    cal = xcals.get_calendar("XNYS")
    sched = cal.schedule.loc[str((now - timedelta(days=count * 2)).date()):str(now.date())]
    rows = [(pd.Timestamp(r["open"]).to_pydatetime(), pd.Timestamp(r["close"]).to_pydatetime())
            for _, r in sched.iterrows()]
    return [r for r in rows if r[1] <= now - timedelta(minutes=16)][-count:]


def fetch_1m(provider: AlpacaBars, symbol: str, days: list[tuple[datetime, datetime]], pause) -> dict:
    out = {"status": "OK", "bars": []}
    for i in range(0, len(days), 10):
        part = provider.bars(symbol, "1m", days[i][0], days[min(i + 9, len(days) - 1)][1])
        pause(1.0)  # shared 200 calls/min Basic limit with other private jobs
        if part.get("status") != "OK":
            return part
        out["bars"].extend(part["bars"])
    return out


def run(symbols: list[str], count: int, now: datetime, env, pause=time.sleep) -> dict:
    provider = AlpacaBars(env, now=now)
    status = provider.status()
    if status != "READY":
        return {"status": status}
    days = sessions(now, count + 40)  # earlier sessions warm up the 1H EMA20, ATR14 and the volume baseline
    study = set(days[-count:])
    order = {d: i for i, d in enumerate(days[-count:])}
    signals: list[cs.Signal] = []
    halves: dict[str, list[cs.Signal]] = {"first_half": [], "second_half": []}
    coverage: dict = {"symbols_ok": 0, "symbols_failed": 0, "sessions": count}
    for symbol in symbols:
        daily = provider.bars(symbol, "1d", now - timedelta(days=(count + 80) * 2), now)
        minute = fetch_1m(provider, symbol, days, pause)
        if daily.get("status") != "OK" or minute.get("status") != "OK":
            coverage["symbols_failed"] += 1
            reason = f"daily={daily.get('status')} 1m={minute.get('status')}"
            coverage.setdefault("failure_reasons", {})[reason] = coverage.get("failure_reasons", {}).get(reason, 0) + 1
            continue
        coverage["symbols_ok"] += 1
        drows = [{"date": b["t"].astimezone(NY).date().isoformat(), "open": b["o"], "high": b["h"],
                  "low": b["l"], "close": b["c"], "volume": b["v"]} for b in daily["bars"]]
        by_day: dict[str, list[dict]] = {}
        for b in minute["bars"]:
            by_day.setdefault(b["t"].astimezone(NY).date().isoformat(), []).append(b)
        hours_hist: list[dict] = []
        vol_hist: list[dict[tuple[int, int], float]] = []
        for open_at, close_at in days:
            key = open_at.astimezone(NY).date().isoformat()
            regular = [b for b in by_day.get(key, []) if open_at <= b["t"] < close_at]
            if (open_at, close_at) in study and len(vol_hist) >= BASELINE_SESSIONS:
                past = [r for r in drows if r["date"] < key]
                atr14 = dp.atr(past[-60:]) if len(past) >= 15 else None
                weekly = dp.weekly_from_daily(past, last_closed_week_end=past[-1]["date"]) if past else []
                baseline: dict[tuple[int, int], float] = {}
                for k in {k for v in vol_hist[-BASELINE_SESSIONS:] for k in v}:
                    vals = [v[k] for v in vol_hist[-BASELINE_SESSIONS:] if k in v]
                    baseline[k] = sum(vals) / len(vals)
                if past and atr14:
                    found = cs.session_signals(regular, open_at, past[-1], atr14, weekly[-1] if weekly else None,
                                               hours_hist[-60:], baseline)
                    signals.extend(found)
                    half = "first_half" if order[(open_at, close_at)] < count // 2 else "second_half"
                    halves[half].extend(found)
            hours_hist.extend(cs.bucket(regular, open_at, 60))
            vol_hist.append({(m, b["idx"]): b["v"] for m in cs.RVOL_FRAMES for b in cs.bucket(regular, open_at, m)})
    compact = {k: {"exp_atr": v.get("exp_atr"), "n": v.get("n")} for k, v in cs.summarise(halves["first_half"]).items()}
    compact2 = {k: {"exp_atr": v.get("exp_atr"), "n": v.get("n")} for k, v in cs.summarise(halves["second_half"]).items()}
    return {"status": "OK", "coverage": coverage, "feed": "SIP historical 1-minute (>= 16 minutes old)",
            "all": cs.summarise(signals), "first_half": compact, "second_half": compact2}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=120)
    args = parser.parse_args()
    result = run([*DETAIL_INDEX_FUNDS, *DETAIL_LEADERS], args.sessions, datetime.now(timezone.utc), os.environ)
    text = json.dumps(result, indent=1)
    print("Confirmation study (aggregate only):", text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Confirmation timeframe study (aggregate only)\n\n```json\n" + text + "\n```\n")
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
