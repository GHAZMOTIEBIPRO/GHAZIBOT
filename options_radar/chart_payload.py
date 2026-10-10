from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd


def build_chart_bars(history: pd.DataFrame, *, max_bars: int = 160) -> list[dict[str, Any]]:
    """Serialize daily OHLC history for TradingView Lightweight Charts."""
    if history is None or history.empty:
        return []
    if max_bars < 20:
        raise ValueError("max_bars must be >= 20")

    lookup = {str(column).lower(): column for column in history.columns}
    required = ("open", "high", "low", "close")
    if any(name not in lookup for name in required):
        return []

    frame = history.tail(max_bars).copy()
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        timestamp = pd.to_datetime(index, errors="coerce")
        if pd.isna(timestamp):
            continue
        values: dict[str, float] = {}
        valid = True
        for name in required:
            value = pd.to_numeric(row.get(lookup[name]), errors="coerce")
            if pd.isna(value):
                valid = False
                break
            values[name] = float(value)
        if not valid:
            continue
        rows.append(
            {
                "time": timestamp.strftime("%Y-%m-%d"),
                "open": round(values["open"], 6),
                "high": round(values["high"], 6),
                "low": round(values["low"], 6),
                "close": round(values["close"], 6),
            }
        )

    deduped: dict[str, dict[str, Any]] = {row["time"]: row for row in rows}
    return [deduped[key] for key in sorted(deduped)]


def build_chart_bundle(
    stocks: list[dict[str, Any]],
    history_loader: Callable[..., pd.DataFrame],
    *,
    max_symbols: int = 6,
    max_bars: int = 160,
    period: str = "6mo",
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    charts: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for stock in stocks[: max(0, max_symbols)]:
        symbol = str(stock.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        try:
            history = history_loader(symbol, period=period)
            bars = build_chart_bars(history, max_bars=max_bars)
            if not bars:
                continue
            charts[symbol] = {
                "bars": bars,
                "levels": {
                    key: stock.get(key)
                    for key in (
                        "price",
                        "entry_low",
                        "entry_high",
                        "target_1",
                        "target_2",
                        "stop",
                    )
                },
                "setup_side": stock.get("setup_side"),
                "technical_direction": stock.get("technical_direction"),
                "source_note": "Uses the same underlying history provider policy as the stock radar.",
            }
        except Exception as exc:
            errors[symbol] = str(exc)
    return charts, errors
