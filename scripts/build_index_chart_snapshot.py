"""Public OHLC chart snapshots from the SAME bounded index fetch cycle.

Research-only Yahoo source. A chart timestamp is a provider bar start or
NY session date, never a fabricated live/executable quote timestamp.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.build_index_context import (
    FIVE_MIN_SYMBOLS, NY, SYMBOLS, bar_minutes, clean_bars, completed_daily,
    four_hour_from_quarters, hourly_from_quarters, last_finished_five_min,
    last_finished_intraday, safe, technical,
)

MAX_BARS = {"1d": 110, "4h": 40, "1h": 90, "15m": 100, "5m": 110}


def pack_bars(frame: pd.DataFrame, *, interval: str) -> list[dict]:
    if frame.empty:
        return []
    if interval not in MAX_BARS:
        raise ValueError("invalid interval")
    output = []
    for timestamp, row in frame.tail(MAX_BARS[interval]).iterrows():
        candle = {
            "time": timestamp.date().isoformat() if interval == "1d"
                    else int(timestamp.tz_convert(timezone.utc).timestamp()),
            "open": safe(row["Open"]), "high": safe(row["High"]),
            "low": safe(row["Low"]), "close": safe(row["Close"]),
        }
        if any(candle[k] is None for k in ("open", "high", "low", "close")):
            continue
        if not (candle["low"] <= min(candle["open"], candle["close"])
                <= max(candle["open"], candle["close"]) <= candle["high"]):
            continue
        output.append(candle)
    return output


def chart_report(
    daily: dict[str, pd.DataFrame], intraday: dict[str, pd.DataFrame],
    five_min: dict[str, pd.DataFrame], *, now: datetime,
) -> dict:
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    output = {}
    for symbol, (provider_ticker, full_name, kind) in SYMBOLS.items():
        frames = {
            "1d": completed_daily(clean_bars(daily.get(symbol), intraday=False), now),
            "15m": last_finished_intraday(clean_bars(intraday.get(symbol), intraday=True), now),
        }
        # Construct 60m only from four consecutive, already completed
        # 15m source candles. No extra Yahoo request or unfinished bar.
        frames["1h"] = hourly_from_quarters(frames["15m"])
        frames["4h"] = four_hour_from_quarters(frames["15m"])
        if symbol in FIVE_MIN_SYMBOLS:
            frames["5m"] = last_finished_five_min(
                clean_bars(five_min.get(symbol), intraday=True), now
            )
        intervals = {}
        for unit, frame in frames.items():
            bars = pack_bars(frame, interval=unit)
            if not bars:
                continue
            last = frame.index[-1]
            # Technical summary aligns to the chart's *last completed* bar.
            signals = technical(frame, fast=9 if unit in ("5m", "1h", "4h") else 20,
                                slow=21 if unit in ("5m", "1h", "4h") else 50)
            local_now = now.astimezone(NY)
            age = (now - last.to_pydatetime().astimezone(timezone.utc)).total_seconds()/60
            complete_age = age - bar_minutes(last, unit) if unit in ("1h", "4h") else age
            current_session = (
                unit != "1d" and last.date() == local_now.date()
                and 0 <= complete_age <= (20 if unit == "5m" else 240 if unit == "4h" else 45)
            )
            intervals[unit] = {
                "bars": bars,
                "last_bar_start_or_session": last.date().isoformat()
                    if unit == "1d" else last.isoformat(),
                "provider_bar_start_age_minutes_at_build": round(age, 1) if unit != "1d" else None,
                "current_session_confirmed": bool(current_session),
                "technical": signals,
                "derived_from": ("four_completed_15m_yahoo_bars" if unit == "1h"
                                 else "session_aligned_completed_15m_yahoo_bars" if unit == "4h"
                                 else None),
                "research_only": True,
            }
        if intervals:
            output[symbol] = {
                "symbol": symbol, "provider_symbol": provider_ticker,
                "name": full_name, "kind": kind,
                "intervals": intervals,
            }
    if not output:
        raise ValueError("No OHLC data validated; preserve previous chart report")
    return {
        "schema": "ghazi.index_charts.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source": "Yahoo Finance via yfinance, unofficial and possibly delayed",
        "provider_source_family": "yahoo",
        "data_role": "RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
        "quote_execution_eligible": False,
        "symbols": output,
        "coverage": {"symbols": len(output),
                     "candle_series": sum(len(v["intervals"]) for v in output.values())},
        "disclaimer": "Completed OHLC bars only. Never infer real-time quotes or options execution permissions.",
    }


def write_chart_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from scripts.build_index_context import fetch_frames
    daily, intraday, five = fetch_frames()
    report = chart_report(daily, intraday, five, now=datetime.now(timezone.utc))
    write_chart_report(args.output, report)
    print("Exported completed OHLC:", report["coverage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
