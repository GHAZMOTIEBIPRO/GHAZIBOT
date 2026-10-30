"""Twelve Data Basic: independent owner-only, no-display US watchlist research.

Runs without Alpaca. One bounded API call per core equity/ETF per checkpoint.
It computes S/R and ORB scenarios entirely in memory but neither publishes
source/derived levels nor transmits them to Telegram/public bots. The output
is only operational health and coverage counts. No option/OPRA authority.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from options_radar.core_options_strategy import technical_levels, ohlcv
from options_radar.focus_universe import FOCUS_STOCKS
from scripts.verify_free_market_sources import _http, _permitted, _positive

NY = ZoneInfo("America/New_York")
CORE_SYMBOLS = tuple(dict.fromkeys(("SPY", "QQQ", *FOCUS_STOCKS)))
# 11 credits (one per symbol) per run, 3 runs/day = 33 of 800 Basic
# daily credits. 12 seconds between requests is below 8/min even without
# assuming the other independent CI jobs do not consume credits.
INTER_REQUEST_SECONDS = 12
MAX_SOURCE_ROWS = 600


def _parse_bars(payload: Any, symbol: str, *, now: datetime) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    meta, rows = payload.get("meta"), payload.get("values")
    if (not isinstance(meta, dict) or meta.get("symbol") != symbol
            or not isinstance(rows, list) or len(rows) > MAX_SOURCE_ROWS):
        return []
    if meta.get("interval") not in ("5min", None):
        return []
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            return []
        t = row.get("datetime")
        if not isinstance(t, str):
            return []
        try:
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return []
        # Explicitly requested Eastern clock time, never assume UTC.
        aware = dt.replace(tzinfo=NY).astimezone(timezone.utc)
        values = [_positive(row.get(field)) for field in ("open", "high", "low", "close")]
        if any(x is None for x in values):
            return []
        volume = row.get("volume")
        try:
            v = float(volume)
        except (ValueError, TypeError):
            return []
        if not 0 <= v < float("inf"):
            return []
        o, h, l, c = values
        if h < max(o, l, c) or l > min(o, h, c):
            return []
        clean.append({"timestamp": aware.isoformat(), "open": o, "high": h,
                      "low": l, "close": c, "volume": v})
    return ohlcv(clean, now=now, minutes=5)


def _daily_from_intraday(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        key = bar["time"].astimezone(NY).date().isoformat()
        sessions[key].append(bar)
    output = []
    for day in sorted(sessions):
        group = sorted(sessions[day], key=lambda row: row["time"])
        # Reject sessions without sufficient traded bars as daily context.
        if len(group) < 26:
            continue
        output.append({
            "timestamp": group[0]["time"].isoformat(),
            "open": group[0]["open"],
            "high": max(x["high"] for x in group),
            "low": min(x["low"] for x in group),
            "close": group[-1]["close"],
            "volume": sum(x["volume"] for x in group),
        })
    return output


def run(env: dict[str, str], *, session: Any = requests,
        now: datetime | None = None, sleep=time.sleep) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware now required")
    result: dict[str, Any] = {
        "schema": "ghazi.twelve_owner_non_display.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "status": "NO_KEY", "source": "TWELVE_DATA_BASIC_NON_DISPLAY",
        "symbols_requested": len(CORE_SYMBOLS),
        "symbols_with_bars": 0, "symbols_with_computed_levels": 0,
        "requests": 0, "rate_limit_reserved_credits": 0,
        "public_display_allowed": False, "telegram_delivery_allowed": False,
        "execution_authority": False, "raw_prices_present": False,
    }
    key = env.get("TWELVE_DATA_API_KEY", "")
    if not key:
        return result
    if not _permitted(env, "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED", "twelve_data"):
        result["status"] = "OWNER_TERMS_NOT_CONFIRMED"
        return result
    result["status"] = "NON_DISPLAY_RESEARCH"
    statuses = []
    for i, sym in enumerate(CORE_SYMBOLS):
        if i:
            sleep(INTER_REQUEST_SECONDS)
        status, payload = _http(
            session, "https://api.twelvedata.com/time_series",
            params={"symbol": sym, "interval": "5min", "outputsize": MAX_SOURCE_ROWS,
                    "timezone": "America/New_York", "apikey": key})
        result["requests"] += 1
        result["rate_limit_reserved_credits"] += 1
        if status != "OK":
            statuses.append(status)
            if status == "QUOTA_EXHAUSTED":
                break
            continue
        if payload.get("status") == "error":
            statuses.append("PROVIDER_REJECTED")
            if payload.get("code") == 429:
                statuses[-1] = "QUOTA_EXHAUSTED"
                break
            continue
        bars = _parse_bars(payload, sym, now=now)
        if len(bars) < 26:
            statuses.append("INSUFFICIENT_COMPLETED_5M")
            continue
        result["symbols_with_bars"] += 1
        daily = _daily_from_intraday(bars)
        # Run the existing tested logic; no output fields depending on IEX
        # or underlying levels are serialized or published. Twelve's VWAP
        # is its own provider-volume VWAP, never called a full SIP NBBO.
        plan = technical_levels(sym, daily, [
            {"timestamp": b["time"].isoformat(),
             "open": b["open"], "high": b["high"], "low": b["low"],
             "close": b["close"], "volume": b["volume"]}
            for b in bars], now=now)
        if plan["status"] == "RESEARCH_ONLY_IEX":
            result["symbols_with_computed_levels"] += 1
            statuses.append("NON_DISPLAY_LEVELS_COMPUTED")
        else:
            statuses.append("BARS_VERIFIED_TECHNICAL_WAIT")
    if "QUOTA_EXHAUSTED" in statuses:
        result["status"] = "QUOTA_EXHAUSTED"
    elif not result["symbols_with_bars"]:
        result["status"] = "NO_VALID_COMPLETED_BARS"
    elif result["symbols_with_computed_levels"]:
        result["status"] = "NON_DISPLAY_LEVELS_COMPUTED"
    else:
        result["status"] = "SOURCE_VERIFIED_NO_ACTIVE_SESSION"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(dict(os.environ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.output)
    # Status counts only, no OHLC, derived support levels or directional calls.
    print("GHAZI Twelve non-display scan:",
          result["status"], "requests=", result["requests"],
          "symbols_with_bars=", result["symbols_with_bars"],
          "research_levels_computed=", result["symbols_with_computed_levels"],
          "execution_ready=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
