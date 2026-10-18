"""No-key US stock watch charts; separate from the execution-grade radar.

Publishes true completed Yahoo OHLC bars for explicitly watched volatile
and large US tickers. No pricing guarantee, no invented missing bars.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.build_index_chart_snapshot import pack_bars
from scripts.build_index_context import (
    NY, clean_bars, completed_daily, last_finished_five_min,
    last_finished_intraday, technical,
)

SMALL_WATCH = ("RGC", "BNAI", "RGTI", "SOUN", "IONQ", "RKLB", "ASTS", "SOFI", "PLTR")
LARGE_WATCH = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD", "MU", "AVGO")
WATCH = SMALL_WATCH + LARGE_WATCH
FIVE_MIN = frozenset(("RGC", "BNAI", "RGTI", "SOUN"))
MAX_BYTES = 700_000


def pack_symbol(
    symbol: str, daily_raw: pd.DataFrame | None,
    minute15_raw: pd.DataFrame | None, minute5_raw: pd.DataFrame | None, *,
    now: datetime,
) -> dict | None:
    if symbol not in WATCH or now.tzinfo is None:
        return None
    clean_day = completed_daily(clean_bars(daily_raw, intraday=False), now)
    clean_15 = last_finished_intraday(clean_bars(minute15_raw, intraday=True), now)
    clean_5 = (last_finished_five_min(clean_bars(minute5_raw, intraday=True), now)
               if symbol in FIVE_MIN else pd.DataFrame())
    sessions = {"1d": clean_day, "15m": clean_15}
    if symbol in FIVE_MIN:
        sessions["5m"] = clean_5
    frame_out = {}
    now_ny = now.astimezone(NY)
    for unit, frame in sessions.items():
        bars = pack_bars(frame, interval=unit)
        if not bars:
            continue
        last = frame.index[-1]
        age = ((now - last.to_pydatetime().astimezone(timezone.utc)).total_seconds()/60
               if unit != "1d" else None)
        same = unit != "1d" and last.date() == now_ny.date()
        frame_out[unit] = {
            "bars": bars,
            "provider_bar_start_or_date": (int(last.timestamp()) if unit != "1d"
                                           else last.date().isoformat()),
            "current_session_confirmed": bool(same and age is not None and
                                              0 <= age <= (20 if unit == "5m" else 45)),
            "technical": technical(frame, fast=9 if unit == "5m" else 20,
                                   slow=21 if unit == "5m" else 50),
            "research_only": True,
        }
    if not frame_out:
        return None
    return {
        "symbol": symbol, "category": "VOLATILE_GROWTH_WATCH" if symbol in SMALL_WATCH
                                      else "LARGE_ESTABLISHED_WATCH",
        "market_cap_verified": False,
        "intervals": frame_out,
        "source": "Yahoo Finance yfinance (unofficial research, may be delayed)",
        "options_execution_grade": False,
    }


def collect(*, now: datetime, provider=None, delay=lambda _: None) -> dict:
    if now.tzinfo is None:
        raise ValueError("aware now required")
    if provider is None:
        import yfinance as provider
    data = {}
    errors = {}
    for symbol in WATCH:
        ticker = provider.Ticker(symbol)
        received = {}
        for unit, period in (("1d", "3mo"), ("15m", "5d"), ("5m", "5d")):
            if unit == "5m" and symbol not in FIVE_MIN:
                continue
            try:
                frame = ticker.history(period=period, interval=unit,
                                       auto_adjust=False, prepost=False)
                if not isinstance(frame, pd.DataFrame) or frame.empty:
                    errors[f"{symbol}_{unit}"] = "NO_OHLC_DATA"
                received[unit] = frame if isinstance(frame, pd.DataFrame) else None
            except Exception as exc:
                errors[f"{symbol}_{unit}"] = type(exc).__name__
                received[unit] = None
            delay(.15)  # bounded transport; do not spin retry on Yahoo rate limit.
        item = pack_symbol(symbol, received.get("1d"), received.get("15m"),
                           received.get("5m"), now=now)
        if item is not None:
            data[symbol] = item
    if not data:
        raise ValueError("No independently valid watched stock candles; preserve old report")
    report = {
        "schema": "ghazi.stock_charts.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "data_role": "RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
        "quote_execution_eligible": False,
        "provider_source_family": "yahoo",
        "symbols": data,
        "coverage": {
            "requested": len(WATCH), "with_valid_charts": len(data),
            "with_daily": sum("1d" in x["intervals"] for x in data.values()),
            "with_15m": sum("15m" in x["intervals"] for x in data.values()),
            "with_5m": sum("5m" in x["intervals"] for x in data.values()),
            "errors": errors,
        },
        "disclaimer": "Free Yahoo OHLC is research-only. No live quote, market-cap certainty, option flow or trade permission.",
    }
    raw=json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(raw.encode())>MAX_BYTES:
        raise ValueError("Stock chart report too large; do not publish invalid payload")
    return report


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    report=collect(now=datetime.now(timezone.utc),delay=time.sleep)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+".tmp")
    temp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",
                    encoding="utf-8")
    temp.replace(args.output)
    print("Stock watch OHLC:",report["coverage"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
