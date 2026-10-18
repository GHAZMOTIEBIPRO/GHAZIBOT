"""Bounded, explicitly stale OHLC retention for rotating free Yahoo watchlists.

Only trusted prior research snapshots qualify. Never turn a cached bar into a
fresh quote, never extend a bar's timestamp and never infer option authority.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

_SOURCE = "Yahoo Finance yfinance (unofficial research, may be delayed)"
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
_NON_STOCK = {"SPX", "NDX", "DJI", "RUT", "VIX", "SPY", "QQQ", "IWM", "DIA"}
_MAX_CACHE_AGE = timedelta(days=7)
_MAX_OLD_BARS = 160


def _timestamp(text):
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_bars(frame, timeframe, now):
    if not isinstance(frame, dict) or frame.get("research_only") is not True:
        return False
    rows = frame.get("bars")
    if not isinstance(rows, list) or not 2 <= len(rows) <= _MAX_OLD_BARS:
        return False
    previous = None
    for bar in rows:
        if not isinstance(bar, dict):
            return False
        value = bar.get("time")
        if timeframe == "1d":
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return False
            try:
                point = date.fromisoformat(value)
            except ValueError:
                return False
            if point > now.date():
                return False
        else:
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            if value < 1_500_000_000 or value > int(now.timestamp()):
                return False
            point = value
        if previous is not None and point <= previous:
            return False
        previous = point
        prices = [bar.get(key) for key in ("open", "high", "low", "close")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in prices):
            return False
        op, hi, lo, cl = prices
        if hi < max(op, cl) or lo > min(op, cl) or lo > hi:
            return False
    return frame.get("provider_bar_start_or_date") == rows[-1]["time"]


def retain_valid_history(previous, current, *, now, actively_scanned, max_extra=12):
    """Return (merged symbols, retained-symbol list, retained-interval count).

    Freshly collected timeframes always win. Up to max_extra formerly scanned
    symbols may remain visible, strictly as historic charts. An old run's
    generated_at does NOT reset the cache clock for a previously retained bar.
    """
    result = dict(current)
    retained = set()
    retained_intervals = 0
    if now.tzinfo is None or not isinstance(previous, dict):
        return result, [], 0
    if (previous.get("schema") != "ghazi.stock_charts.v1"
            or previous.get("provider_source_family") != "yahoo"
            or previous.get("quote_execution_eligible") is not False
            or previous.get("data_role") != "RESEARCH_ONLY_NOT_LICENSED_EXECUTION"):
        return result, [], 0
    published = _timestamp(previous.get("generated_at"))
    if published is None or not timedelta(0) <= now - published <= _MAX_CACHE_AGE:
        return result, [], 0
    symbols = previous.get("symbols")
    if not isinstance(symbols, dict):
        return result, [], 0

    # Other previously scanned symbols use their own source age and are capped.
    # Retain active symbol gaps first; do not evict them for old discoveries.
    active = set(actively_scanned)
    names = [s for s in symbols if s in active]
    old = [s for s in symbols if s not in active]
    names += old[:max_extra]
    for symbol in names:
        if (not isinstance(symbol, str) or not _TICKER.fullmatch(symbol)
                or symbol in _NON_STOCK):
            continue
        item = symbols.get(symbol)
        if not isinstance(item, dict) or item.get("options_execution_grade") is not False:
            continue
        if item.get("market_cap_verified") is not False or item.get("source") != _SOURCE:
            continue
        first = _timestamp(item.get("cached_source_generated_at") or previous["generated_at"])
        if first is None or not timedelta(0) <= now - first <= _MAX_CACHE_AGE:
            continue
        intervals = item.get("intervals")
        if not isinstance(intervals, dict):
            continue
        existing = result.get(symbol)
        present = dict(existing.get("intervals") or {}) if isinstance(existing, dict) else {}
        additions = {}
        for timeframe in ("1d", "1h", "15m", "5m"):
            frame = intervals.get(timeframe)
            if timeframe not in present and _valid_bars(frame, timeframe, now):
                preserved = dict(frame)
                preserved["current_session_confirmed"] = False
                preserved["historical_cache_only"] = True
                preserved["cached_source_generated_at"] = first.isoformat()
                additions[timeframe] = preserved
        if not additions:
            continue
        if existing is None:
            result[symbol] = {
                "symbol": symbol,
                "category": ("VOLATILE_GROWTH_WATCH" if item.get("category") ==
                             "VOLATILE_GROWTH_WATCH" else "HISTORICAL_DISCOVERY_WATCH"),
                "market_cap_verified": False,
                "intervals": additions,
                "source": _SOURCE,
                "options_execution_grade": False,
                "cached_source_generated_at": first.isoformat(),
                "historical_cache_only": True,
            }
        else:
            updated = dict(existing)
            updated["intervals"] = {**present, **additions}
            updated["has_retained_timeframes"] = True
            result[symbol] = updated
        retained.add(symbol)
        retained_intervals += len(additions)
    return result, sorted(retained), retained_intervals
