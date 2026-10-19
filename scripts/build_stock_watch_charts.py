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
from options_radar.stock_watch_confluence import price_confluence_shadow
from scripts.build_index_chart_snapshot import pack_bars
from scripts.build_index_context import (
    NY,
    clean_bars,
    completed_daily,
    hourly_from_quarters,
    last_finished_five_min,
    last_finished_intraday,
    technical,
)
from scripts.stock_chart_retention import retain_valid_history
from scripts.stock_watch_news_attention import load_news_attention, news_candidates

SMALL_WATCH = ("RGC", "BNAI", "RGTI", "SOUN", "IONQ", "RKLB", "ASTS", "SOFI", "PLTR")
LARGE_WATCH = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD", "MU", "AVGO")
WATCH = SMALL_WATCH + LARGE_WATCH
FIVE_MIN = frozenset(WATCH)  # Completed 5m Yahoo history on every fixed watch symbol
MAX_BYTES = 700_000
MAX_DYNAMIC = 4
# Calendar-day freshness guard for completed OHLC observations, not quote latency.
# Accommodates weekends and US market holidays while rejecting weeks-old Yahoo snapshots.
MAX_SOURCE_BAR_AGE_DAYS = 7
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


def load_dynamic_symbols(path: Path | None, *, now: datetime,
                         news_path: Path | None = None) -> tuple[str, ...]:
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
    # Keep top two scored radar discoveries and rotate remaining candidates.
    # Free news only fills spare slots; it never raises the score of a symbol.
    primary = candidates[:2]
    tail = candidates[2:]
    if tail:
        shift = int(now.timestamp() // (6 * 3600)) % len(tail)
        tail = tail[shift:] + tail[:shift]
    ranked = tuple(c for c in primary + tail if c not in WATCH)[:MAX_DYNAMIC]
    attention = load_news_attention(news_path, now=now) if news_path else {}
    if attention:
        return news_candidates(
            attention, fixed=WATCH, radar_choices=ranked, maximum=MAX_DYNAMIC
        )
    return valid_dynamic_symbols(ranked)


def session_vwap_shadow(frame: pd.DataFrame) -> dict:
    """Session VWAP from completed source OHLCV, not last-trade or OPRA data."""
    base = {
        "available": False, "value": None, "session_date": None,
        "source_last_bar_start": None, "research_only": True,
        "source_family": "yahoo", "options_execution_eligible": False,
    }
    if (not isinstance(frame, pd.DataFrame) or frame.empty
            or not isinstance(frame.index, pd.DatetimeIndex)
            or frame.index.tz is None
            or not all(k in frame.columns for k in ("High", "Low", "Close", "Volume"))):
        return base
    local = frame.index.tz_convert(NY)
    last_date = local[-1].date()
    day = frame.loc[local.date == last_date]
    if len(day) < 2:
        return base
    vol = pd.to_numeric(day["Volume"], errors="coerce")
    high = pd.to_numeric(day["High"], errors="coerce")
    low = pd.to_numeric(day["Low"], errors="coerce")
    close = pd.to_numeric(day["Close"], errors="coerce")
    total = float(vol.sum())
    if (not math.isfinite(total) or total <= 0
            or not bool((vol >= 0).all())
            or not bool(((high >= low) & (low > 0) & (close > 0)).all())):
        return base
    typical = (high + low + close) / 3.0
    value = float((typical * vol).sum() / total)
    if not math.isfinite(value) or value <= 0:
        return base
    return {
        **base, "available": True, "value": round(value, 4),
        "session_date": last_date.isoformat(),
        "source_last_bar_start": int(frame.index[-1].timestamp()),
        "completed_bars": len(day),
        "formula": "sum(typical_price_x_source_volume)/sum(source_volume)",
    }


def pack_symbol(
    symbol: str, daily_raw: pd.DataFrame | None,
    minute15_raw: pd.DataFrame | None, minute5_raw: pd.DataFrame | None, *,
    now: datetime, dynamic_watch: tuple[str, ...] = (),
    news_attention: dict | None = None,
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
    any_recent_source_bar = False
    for unit, frame in sessions.items():
        bars = pack_bars(frame, interval=unit)
        if not bars:
            continue
        last = frame.index[-1]
        age = ((now - last.to_pydatetime().astimezone(timezone.utc)).total_seconds()/60
               if unit != "1d" else None)
        same = unit != "1d" and last.date() == now_ny.date()
        complete_age = age - 60 if unit == "1h" and age is not None else age
        if unit == "1d":
            session_age_days = (now_ny.date() - last.date()).days
            source_recent = 0 <= session_age_days <= MAX_SOURCE_BAR_AGE_DAYS
        else:
            closed_age_minutes = age - {"1h": 60, "15m": 15, "5m": 5}[unit]
            source_recent = (-5 <= closed_age_minutes
                             <= MAX_SOURCE_BAR_AGE_DAYS * 24 * 60)
        any_recent_source_bar = any_recent_source_bar or source_recent
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
            "source_recency_verified": source_recent,
        }
        if unit != "1d":
            frame_out[unit]["session_vwap"] = session_vwap_shadow(frame)
    # A successful Yahoo response can return only stale historical candles.
    # Never count such a stock as freshly observed or roll the report clock forward.
    # The separate retained-history path can still display previous bars as historical.
    if not frame_out or not any_recent_source_bar:
        return None
    # Completed DAILY OHLC only. No new Yahoo requests, no changed radar
    # scores, and no falsely independent data provider claim.
    volatility_shadow = bollinger_compression_shadow(clean_day)
    confluence = price_confluence_shadow(clean_day)
    media = (news_attention or {}).get(symbol)
    return {
        "symbol": symbol, "category": ("VOLATILE_GROWTH_WATCH" if symbol in SMALL_WATCH
                                      else "RADAR_DISCOVERY_WATCH" if symbol in dynamic_watch
                                      else "LARGE_ESTABLISHED_WATCH"),
        "market_cap_verified": False,
        "intervals": frame_out,
        "source": "Yahoo Finance yfinance (unofficial research, may be delayed)",
        "options_execution_grade": False,
        "volatility_shadow": volatility_shadow,
        "price_confluence": confluence,
        "news_attention": media if isinstance(media, dict) else None,
    }


def collect(*, now: datetime, provider=None, delay=lambda _: None,
            dynamic_symbols=(), previous=None, news_attention=None) -> dict:
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
            except Exception as exc:  # noqa: BLE001 - Yahoo client may throw arbitrary failures
                errors[f"{symbol}_{unit}"] = type(exc).__name__
                received[unit] = None
            delay(.15)  # bounded transport; do not spin retry on Yahoo rate limit.
        item = pack_symbol(symbol, received.get("1d"), received.get("15m"),
                           received.get("5m"), now=now, dynamic_watch=dynamic,
                           news_attention=news_attention)
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
            "source_recency_max_calendar_days": MAX_SOURCE_BAR_AGE_DAYS,
            "fresh_symbols_meaning": "At least one actual completed source bar within the permitted calendar-day window; not a live quote",
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
    p.add_argument("--news-source",type=Path,default=None)
    args=p.parse_args()
    now=datetime.now(timezone.utc)
    media=load_news_attention(args.news_source, now=now)
    dynamic=load_dynamic_symbols(
        args.discovery_source, now=now, news_path=args.news_source
    )
    previous=None
    if args.output.is_file() and args.output.stat().st_size <= 800_000:
        try:
            previous=json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous=None
    report=collect(now=now,delay=time.sleep,dynamic_symbols=dynamic,
                   previous=previous,news_attention=media)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+".tmp")
    temp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",
                    encoding="utf-8")
    temp.replace(args.output)
    print("Stock watch OHLC:",report["coverage"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
