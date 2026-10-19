"""No-key US stock watch charts; separate from the execution-grade radar.

Publishes true completed Yahoo OHLC bars for explicitly watched volatile
and large US tickers. No pricing guarantee, no invented missing bars.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from options_radar.pandas_ta_bollinger_shadow import bollinger_compression_shadow
from scripts.build_index_chart_snapshot import pack_bars
from scripts.build_index_context import (
    NY, clean_bars, completed_daily, hourly_from_quarters,
    last_finished_five_min, last_finished_intraday, technical,
)
from scripts.stock_chart_retention import retain_valid_history

SMALL_WATCH = ("RGC", "BNAI", "RGTI", "SOUN", "IONQ", "RKLB", "ASTS", "SOFI", "PLTR")
LARGE_WATCH = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD", "MU", "AVGO")
WATCH = SMALL_WATCH + LARGE_WATCH
FIVE_MIN = frozenset(WATCH)  # Completed 5m Yahoo history on every fixed watch symbol
MAX_BYTES = 700_000
MAX_DYNAMIC = 4
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
_NON_STOCK = frozenset(("SPX", "NDX", "DJI", "RUT", "VIX", "SPY", "QQQ", "IWM", "DIA"))


def valid_dynamic_symbols(symbols) -> tuple[str, ...]:
    """Only stock-like identifiers from a trusted radar snapshot, never URLs."""
    out = []
    for value in symbols:
        if not isinstance(value, str):
            continue
        symbol = value.strip().upper()
        if (_SYMBOL.fullmatch(symbol) and symbol not in WATCH
                and symbol not in _NON_STOCK and symbol not in out):
            out.append(symbol)
        if len(out) >= MAX_DYNAMIC:
            break
    return tuple(out)


def load_dynamic_symbols(path: Path | None, *, now: datetime) -> tuple[str, ...]:
    """Rotate new radar discoveries without increasing the fixed Yahoo budget.

    Expired, malformed or future-dated decision snapshots NEVER seed a fetch.
    Chart selection is independent from option-signal authorization.
    """
    if path is None or now.tzinfo is None:
        return ()
    try:
        if path.stat().st_size > 180_000:
            return ()
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schema") != "ghazi.public_decision.v1":
            return ()
        timestamp = report.get("source_generated_at") or report.get("generated_at")
        when = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if when.tzinfo is None:
            return ()
        age = (now - when).total_seconds()
        if not (-300 <= age <= 72 * 3600):
            return ()
        rows = report.get("stocks")
        if not isinstance(rows, list):
            return ()
    except (OSError, ValueError, TypeError, AttributeError):
        return ()
    ranked = []
    for row in rows[:150]:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        score = row.get("score")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            continue
        if symbol in WATCH or symbol in _NON_STOCK:
            continue
        if not isinstance(score, (int, float)) or not math.isfinite(score):
            continue
        ranked.append((float(score), symbol))
    candidates = list(dict.fromkeys(
        symbol for _, symbol in sorted(ranked, key=lambda x: -x[0])
    ))
    if len(candidates) <= MAX_DYNAMIC:
        return valid_dynamic_symbols(candidates)
    # Keep top two actionable research sightings, rotate remaining slots
    # every six hours so lower-ranked new symbols are not forever uncharted.
    primary = candidates[:2]
    tail = candidates[2:]
    shift = int(now.timestamp() // (6 * 3600)) % len(tail)
    rotating = tail[shift:] + tail[:shift]
    return valid_dynamic_symbols(primary + rotating[:MAX_DYNAMIC - 2])


def pack_symbol(
    symbol: str, daily_raw: pd.DataFrame | None,
    minute15_raw: pd.DataFrame | None, minute5_raw: pd.DataFrame | None, *,
    now: datetime, dynamic_watch: tuple[str, ...] = (),
) -> dict | None:
    if (symbol not in WATCH and symbol not in dynamic_watch) or now.tzinfo is None:
        return None
    clean_day = completed_daily(clean_bars(daily_raw, intraday=False), now)
    clean_15 = last_finished_intraday(clean_bars(minute15_raw, intraday=True), now)
    needs_5m = symbol in FIVE_MIN or symbol in dynamic_watch
    clean_5 = (last_finished_five_min(clean_bars(minute5_raw, intraday=True), now)
               if needs_5m else pd.DataFrame())
    sessions = {"1d": clean_day, "15m": clean_15,
                "1h": hourly_from_quarters(clean_15)}
    if needs_5m:
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
        complete_age = age - 60 if unit == "1h" and age is not None else age
        frame_out[unit] = {
            "bars": bars,
            "provider_bar_start_or_date": (int(last.timestamp()) if unit != "1d"
                                           else last.date().isoformat()),
            "current_session_confirmed": bool(
                same and complete_age is not None and
                0 <= complete_age <= (20 if unit == "5m" else 45)
            ),
            "technical": technical(frame, fast=9 if unit in ("5m", "1h") else 20,
                                   slow=21 if unit in ("5m", "1h") else 50),
            "derived_from": ("four_completed_15m_yahoo_bars" if unit == "1h" else None),
            "research_only": True,
        }
    if not frame_out:
        return None
    # Completed DAILY OHLC only. No new Yahoo requests, no changed radar
    # scores, and no falsely independent data provider claim.
    volatility_shadow = bollinger_compression_shadow(clean_day)
    return {
        "symbol": symbol, "category": ("VOLATILE_GROWTH_WATCH" if symbol in SMALL_WATCH
                                      else "RADAR_DISCOVERY_WATCH" if symbol in dynamic_watch
                                      else "LARGE_ESTABLISHED_WATCH"),
        "market_cap_verified": False,
        "intervals": frame_out,
        "source": "Yahoo Finance yfinance (unofficial research, may be delayed)",
        "options_execution_grade": False,
        "volatility_shadow": volatility_shadow,
    }


def collect(*, now: datetime, provider=None, delay=lambda _: None,
            dynamic_symbols=(), previous=None) -> dict:
    if now.tzinfo is None:
        raise ValueError("aware now required")
    if provider is None:
        import yfinance as provider
    dynamic = valid_dynamic_symbols(dynamic_symbols)
    watch = WATCH + dynamic
    data = {}
    errors = {}
    for symbol in watch:
        ticker = provider.Ticker(symbol)
        received = {}
        for unit, period in (("1d", "3mo"), ("15m", "5d"), ("5m", "5d")):
            if unit == "5m" and symbol not in FIVE_MIN and symbol not in dynamic:
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
                           received.get("5m"), now=now, dynamic_watch=dynamic)
        if item is not None:
            data[symbol] = item
    if not data:
        raise ValueError("No independently valid watched stock candles; preserve old report")
    # Cached bars are explicitly historical; never count them as fresh
    # observations or conceal provider failures.
    fresh = dict(data)
    data, retained, retained_intervals = retain_valid_history(
        previous, data, now=now, actively_scanned=watch, max_extra=12
    )
    report = {
        "schema": "ghazi.stock_charts.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "data_role": "RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
        "quote_execution_eligible": False,
        "provider_source_family": "yahoo",
        "symbols": data,
        "coverage": {
            "requested": len(watch), "with_valid_charts": len(fresh),
            "fresh_symbols": sorted(fresh),
            "retained_symbols": retained,
            "retained_symbols_count": len(retained),
            "retained_timeframes_count": retained_intervals,
            "historical_only_symbols": sorted(set(data) - set(fresh)),
            "charts_including_historical": len(data),
            "retention_max_days": 7,
            "discovered_requested": len(dynamic),
            "discovered_symbols": list(dynamic),
            "discovered_with_charts": sum(s in fresh for s in dynamic),
            "with_daily": sum("1d" in x["intervals"] for x in fresh.values()),
            "with_15m": sum("15m" in x["intervals"] for x in fresh.values()),
            "with_1h": sum("1h" in x["intervals"] for x in fresh.values()),
            "with_5m": sum("5m" in x["intervals"] for x in fresh.values()),
            "with_daily_including_historical": sum(
                "1d" in x["intervals"] for x in data.values()),
            "with_15m_including_historical": sum(
                "15m" in x["intervals"] for x in data.values()),
            "with_1h_including_historical": sum(
                "1h" in x["intervals"] for x in data.values()),
            "with_5m_including_historical": sum(
                "5m" in x["intervals"] for x in data.values()),
            "errors": errors,
        },
        "disclaimer": ("Free Yahoo OHLC is research-only; retained bars may be days old "
                       "and never become live quotes. No market-cap certainty, "
                       "option flow or trade permission."),
    }
    raw=json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(raw.encode())>MAX_BYTES:
        raise ValueError("Stock chart report too large; do not publish invalid payload")
    return report


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--discovery-source",type=Path,default=None)
    args=p.parse_args()
    now=datetime.now(timezone.utc)
    dynamic=load_dynamic_symbols(args.discovery_source,now=now)
    previous=None
    if args.output.is_file() and args.output.stat().st_size <= 800_000:
        try:
            previous=json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous=None
    report=collect(now=now,delay=time.sleep,dynamic_symbols=dynamic,previous=previous)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+".tmp")
    temp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",
                    encoding="utf-8")
    temp.replace(args.output)
    print("Stock watch OHLC:",report["coverage"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
