from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

from .advanced_signals import is_standard_occ_contract
from .hybrid_fetcher import OPTION_COLUMNS
from .settings import Settings


def _number(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(*values: Any) -> pd.Timestamp:
    for value in values:
        if value in (None, ""):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            stamp = pd.to_datetime(value, utc=True, errors="coerce")
        else:
            absolute = abs(numeric)
            unit = "ns" if absolute >= 100_000_000_000_000_000 else "ms" if absolute >= 100_000_000_000 else "s"
            stamp = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        if not pd.isna(stamp):
            return stamp
    return pd.Timestamp(datetime.now(timezone.utc))


def _option_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OPTION_COLUMNS)
    frame = pd.DataFrame(rows)
    for column in OPTION_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    return frame[OPTION_COLUMNS]


def polygon_option_chain(
    settings: Settings,
    symbol: str,
    min_dte: int,
    max_dte: int,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch an OPRA-backed option-chain snapshot from Polygon/Massive.

    The connector is entitlement-aware: HTTP 401/403/404 errors are allowed to
    bubble into the existing provider audit instead of being hidden.
    """

    token = settings.polygon_api_key
    if not token:
        raise RuntimeError("POLYGON_API_KEY is not configured")
    client = session or requests.Session()
    today = date.today()
    params: dict[str, Any] = {
        "apiKey": token,
        "limit": 250,
        "expiration_date.gte": (today + timedelta(days=min_dte)).isoformat(),
        "expiration_date.lte": (today + timedelta(days=max_dte)).isoformat(),
    }
    url = f"https://api.polygon.io/v3/snapshot/options/{symbol.upper()}"
    rows: list[dict[str, Any]] = []
    pages = 0
    while url and pages < 8:
        response = client.get(url, params=params if pages == 0 else {"apiKey": token}, timeout=settings.request_timeout_seconds)
        response.raise_for_status()
        payload = response.json() or {}
        for item in payload.get("results") or []:
            details = item.get("details") or {}
            quote = item.get("last_quote") or {}
            trade = item.get("last_trade") or {}
            day = item.get("day") or {}
            greeks = item.get("greeks") or {}
            underlying = item.get("underlying_asset") or {}
            contract = str(details.get("ticker") or "").removeprefix("O:").replace(" ", "")
            expiration_text = details.get("expiration_date")
            expiration = pd.to_datetime(expiration_text, utc=True, errors="coerce")
            if pd.isna(expiration):
                continue
            dte = (expiration.date() - today).days
            bid = _number(quote.get("bid"))
            ask = _number(quote.get("ask"))
            last = _number(trade.get("price"), _number(day.get("close")))
            mid = (bid + ask) / 2.0 if math.isfinite(bid) and math.isfinite(ask) else np.nan
            spread = (ask - bid) / ask if math.isfinite(bid) and math.isfinite(ask) and ask > 0 else np.nan
            option_type = str(details.get("contract_type") or "").lower()
            updated_at = _timestamp(
                trade.get("sip_timestamp"),
                quote.get("sip_timestamp"),
                trade.get("participant_timestamp"),
                quote.get("participant_timestamp"),
            )
            rows.append(
                {
                    "contract_symbol": contract,
                    "symbol": symbol.upper(),
                    "expiration": expiration,
                    "strike": _number(details.get("strike_price")),
                    "option_type": option_type,
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "volume": int(_number(day.get("volume"), 0.0)),
                    "open_interest": int(_number(item.get("open_interest"), 0.0)),
                    "iv": _number(item.get("implied_volatility")),
                    "delta": _number(greeks.get("delta")),
                    "gamma": _number(greeks.get("gamma")),
                    "theta": _number(greeks.get("theta")),
                    "vega": _number(greeks.get("vega")),
                    "underlying_price": _number(underlying.get("price")),
                    "updated_at": updated_at,
                    "source": "polygon_options",
                    "data_quality": 0.98,
                    "freshness_label": "Polygon/Massive OPRA snapshot; freshness depends on plan",
                    "greeks_method": "provider",
                    "dte": dte,
                    "spread_pct": spread,
                    "standard_contract": is_standard_occ_contract(contract),
                    "quality_passed": True,
                    "rejection_reason": "",
                    "mid": mid,
                }
            )
        url = payload.get("next_url")
        pages += 1
    return _option_frame(rows)


def alpaca_option_snapshots(
    settings: Settings,
    contract_symbols: list[str],
    *,
    session: requests.Session | None = None,
) -> dict[str, dict[str, Any]]:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY are not configured")
    symbols = [str(value).replace("O:", "").replace(" ", "") for value in contract_symbols if value]
    if not symbols:
        return {}
    client = session or requests.Session()
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
    }
    output: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(symbols), 100):
        batch = symbols[offset : offset + 100]
        response = client.get(
            "https://data.alpaca.markets/v1beta1/options/snapshots",
            params={"symbols": ",".join(batch), "feed": settings.alpaca_options_feed, "limit": 1000},
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json() or {}
        snapshots = payload.get("snapshots") or {}
        for contract, item in snapshots.items():
            quote = item.get("latestQuote") or item.get("latest_quote") or {}
            trade = item.get("latestTrade") or item.get("latest_trade") or {}
            greeks = item.get("greeks") or {}
            output[str(contract).replace("O:", "")] = {
                "source": "alpaca_options",
                "feed": settings.alpaca_options_feed,
                "bid": _number(quote.get("bp") or quote.get("bid_price")),
                "ask": _number(quote.get("ap") or quote.get("ask_price")),
                "last": _number(trade.get("p") or trade.get("price")),
                "delta": _number(greeks.get("delta")),
                "gamma": _number(greeks.get("gamma")),
                "theta": _number(greeks.get("theta")),
                "vega": _number(greeks.get("vega")),
                "iv": _number(item.get("impliedVolatility") or item.get("implied_volatility")),
                "updated_at": str(quote.get("t") or trade.get("t") or ""),
            }
    return output


def alpaca_stock_snapshots(
    settings: Settings,
    symbols: list[str],
    *,
    session: requests.Session | None = None,
) -> dict[str, dict[str, Any]]:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY are not configured")
    clean = [str(value).strip().upper() for value in symbols if str(value).strip()]
    if not clean:
        return {}
    client = session or requests.Session()
    response = client.get(
        "https://data.alpaca.markets/v2/stocks/snapshots",
        params={"symbols": ",".join(clean[:200]), "feed": settings.alpaca_stock_feed},
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        },
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json() or {}
    output: dict[str, dict[str, Any]] = {}
    for symbol, item in payload.items():
        trade = item.get("latestTrade") or item.get("latest_trade") or {}
        quote = item.get("latestQuote") or item.get("latest_quote") or {}
        daily = item.get("dailyBar") or item.get("daily_bar") or {}
        output[str(symbol).upper()] = {
            "source": "alpaca",
            "feed": settings.alpaca_stock_feed,
            "last": _number(trade.get("p") or trade.get("price"), _number(daily.get("c") or daily.get("close"))),
            "bid": _number(quote.get("bp") or quote.get("bid_price")),
            "ask": _number(quote.get("ap") or quote.get("ask_price")),
            "volume": _number(daily.get("v") or daily.get("volume"), 0.0),
            "updated_at": str(trade.get("t") or quote.get("t") or ""),
        }
    return output
