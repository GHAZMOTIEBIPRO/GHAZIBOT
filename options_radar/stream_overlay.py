from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value: Any) -> pd.Timestamp | None:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(stamp) else stamp


def _age_seconds(value: Any) -> float | None:
    stamp = _timestamp(value)
    if stamp is None:
        return None
    return max(0.0, (pd.Timestamp.now(tz="UTC") - stamp).total_seconds())


def load_stream_snapshot(
    path: str | Path | None = None,
    *,
    max_age_seconds: float | None = None,
) -> dict[str, Any] | None:
    source = Path(path or os.getenv("DATA_FABRIC_STREAM_SNAPSHOT", "data/live/stream_snapshot.json"))
    maximum = float(max_age_seconds or os.getenv("DATA_FABRIC_STREAM_MAX_AGE_SECONDS", "20"))
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    age = _age_seconds(payload.get("generated_at"))
    if age is None or age > maximum:
        return None
    return payload


def _event(record: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = record.get(name)
        if isinstance(value, dict):
            return value
    return {}


def option_stream_reference(
    contract_symbol: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    snapshot = snapshot or load_stream_snapshot()
    if not snapshot:
        return None
    contract = str(contract_symbol or "").upper().replace(" ", "")
    record = (snapshot.get("options") or {}).get(contract)
    if not isinstance(record, dict):
        return None
    quote = _event(record, "q", "quote")
    trade = _event(record, "t", "trade")
    quote_time = quote.get("t") or quote.get("timestamp") or record.get("last_event_at")
    trade_time = trade.get("t") or trade.get("timestamp") or record.get("last_event_at")
    return {
        "contract_symbol": contract,
        "feed": str(snapshot.get("option_feed") or "indicative").lower(),
        "bid": _number(quote.get("bp") or quote.get("bid_price")),
        "ask": _number(quote.get("ap") or quote.get("ask_price")),
        "bid_size": _number(quote.get("bs") or quote.get("bid_size")),
        "ask_size": _number(quote.get("as") or quote.get("ask_size")),
        "last": _number(trade.get("p") or trade.get("price")),
        "trade_size": _number(trade.get("s") or trade.get("size")),
        "quote_at": quote_time,
        "trade_at": trade_time,
        "quote_age_seconds": _age_seconds(quote_time),
        "trade_age_seconds": _age_seconds(trade_time),
    }


def overlay_option_chain_from_stream(
    chain: pd.DataFrame,
    snapshot: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if chain is None or chain.empty:
        return chain, {"available": False, "matched": 0, "execution_quotes_replaced": 0}
    snapshot = snapshot or load_stream_snapshot()
    if not snapshot:
        return chain.copy(), {"available": False, "matched": 0, "execution_quotes_replaced": 0}
    out = chain.copy()
    matched = 0
    replaced = 0
    feed = str(snapshot.get("option_feed") or "indicative").lower()
    maximum = float(os.getenv("DATA_FABRIC_STREAM_MAX_AGE_SECONDS", "20"))

    for idx, row in out.iterrows():
        reference = option_stream_reference(str(row.get("contract_symbol") or ""), snapshot)
        if not reference:
            continue
        matched += 1
        bid, ask, last = reference["bid"], reference["ask"], reference["last"]
        quote_age = reference.get("quote_age_seconds")
        trade_age = reference.get("trade_age_seconds")
        out.at[idx, "stream_feed"] = feed
        out.at[idx, "stream_bid"] = bid or None
        out.at[idx, "stream_ask"] = ask or None
        out.at[idx, "stream_last"] = last or None
        out.at[idx, "stream_quote_age_seconds"] = quote_age
        out.at[idx, "stream_trade_age_seconds"] = trade_age
        out.at[idx, "stream_execution_grade"] = feed == "opra"

        # Only an entitled OPRA stream may replace execution quotes. Indicative
        # data remains visible for context but is never promoted to NBBO.
        if feed != "opra" or quote_age is None or quote_age > maximum:
            continue
        if bid <= 0 or ask < bid or ask <= 0:
            continue
        out.at[idx, "bid"] = bid
        out.at[idx, "ask"] = ask
        if last > 0 and trade_age is not None and trade_age <= maximum:
            out.at[idx, "last"] = last
        out.at[idx, "updated_at"] = reference.get("quote_at") or reference.get("trade_at")
        existing_source = str(row.get("source") or "")
        out.at[idx, "source"] = f"{existing_source} + alpaca_opra_stream".strip(" +")
        out.at[idx, "freshness_label"] = "Alpaca OPRA stream; execution-grade quote overlay"
        out.at[idx, "data_quality"] = max(0.96, _number(row.get("data_quality")))
        out.at[idx, "fabric_quote_provider"] = "alpaca_opra_stream"
        out.at[idx, "fabric_source_tier"] = "LIVE_OR_LICENSED"
        replaced += 1

    return out, {
        "available": True,
        "feed": feed,
        "matched": matched,
        "execution_quotes_replaced": replaced,
        "execution_grade": feed == "opra",
        "max_age_seconds": maximum,
    }


def stock_stream_reference(
    symbol: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    snapshot = snapshot or load_stream_snapshot()
    if not snapshot:
        return None
    normalized = str(symbol or "").upper().strip()
    record = (snapshot.get("stocks") or {}).get(normalized)
    if not isinstance(record, dict):
        return None
    quote = _event(record, "q", "quote")
    trade = _event(record, "t", "trade")
    bid = _number(quote.get("bp") or quote.get("bid_price"))
    ask = _number(quote.get("ap") or quote.get("ask_price"))
    last = _number(trade.get("p") or trade.get("price"))
    event_at = trade.get("t") or quote.get("t") or record.get("last_event_at")
    reference_price = last if last > 0 else ((bid + ask) / 2.0 if bid > 0 and ask >= bid else 0.0)
    return {
        "symbol": normalized,
        "feed": str(snapshot.get("stock_feed") or "iex").lower(),
        "reference_price": reference_price,
        "bid": bid,
        "ask": ask,
        "last": last,
        "event_at": event_at,
        "age_seconds": _age_seconds(event_at),
    }
