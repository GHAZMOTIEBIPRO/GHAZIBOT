from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd
import requests
import yfinance as yf

from .settings import Settings

LOGGER = logging.getLogger(__name__)
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


@dataclass(frozen=True)
class BarResult:
    frame: pd.DataFrame
    source: str
    freshness: str


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV)


def _normalise(frame: pd.DataFrame, *, index: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty()
    out = frame.copy()
    if index and index in out.columns:
        out.index = pd.to_datetime(out.pop(index), utc=True, errors="coerce")
    else:
        out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    rename = {str(column).lower(): column for column in out.columns}
    selected: dict[str, pd.Series] = {}
    for target in OHLCV:
        source = rename.get(target.lower())
        if source is not None:
            selected[target] = pd.to_numeric(out[source], errors="coerce")
    result = pd.DataFrame(selected, index=out.index)
    for missing in OHLCV:
        if missing not in result:
            result[missing] = 0 if missing == "Volume" else pd.NA
    return result[OHLCV].dropna(subset=["Open", "High", "Low", "Close"]).sort_index()


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    mapping = {
        "1mo": 35,
        "3mo": 100,
        "6mo": 200,
        "1y": 380,
        "2y": 760,
        "5y": 1900,
    }
    return now - timedelta(days=mapping.get(period, 380))


def _yahoo(symbol: str, *, period: str, interval: str, start: datetime | None = None,
           end: datetime | None = None) -> BarResult:
    kwargs: dict[str, Any] = {
        "interval": interval,
        "auto_adjust": False,
        "progress": False,
        "threads": False,
    }
    if start is not None:
        kwargs["start"] = start
        kwargs["end"] = end or datetime.now(timezone.utc)
    else:
        kwargs["period"] = period
    data = yf.download(symbol, **kwargs)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return BarResult(_normalise(data), "yahoo/yfinance", "unofficial / may be delayed")


def _tradier(settings: Settings, symbol: str, *, interval: str, start: datetime,
             end: datetime) -> BarResult:
    if not settings.tradier_token:
        raise RuntimeError("TRADIER_TOKEN is not configured")
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {settings.tradier_token}",
        "Accept": "application/json",
    })
    if interval == "1d":
        response = session.get(
            f"{settings.tradier_base_url}/v1/markets/history",
            params={
                "symbol": symbol,
                "interval": "daily",
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
            },
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json().get("history", {}).get("day", [])
        if isinstance(rows, dict):
            rows = [rows]
        frame = pd.DataFrame(rows or [])
        if not frame.empty:
            frame = frame.rename(columns={
                "date": "timestamp", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            })
        freshness = "Tradier sandbox: 15-minute delayed" if "sandbox" in settings.tradier_base_url else "Tradier brokerage feed"
        return BarResult(_normalise(frame, index="timestamp"), "tradier", freshness)

    response = session.get(
        f"{settings.tradier_base_url}/v1/markets/timesales",
        params={
            "symbol": symbol,
            "interval": "5min",
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
            "session_filter": "open",
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json().get("series", {}).get("data", [])
    if isinstance(rows, dict):
        rows = [rows]
    frame = pd.DataFrame(rows or [])
    if not frame.empty:
        frame = frame.rename(columns={
            "time": "timestamp", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        })
    freshness = "Tradier sandbox: 15-minute delayed" if "sandbox" in settings.tradier_base_url else "Tradier brokerage feed"
    return BarResult(_normalise(frame, index="timestamp"), "tradier", freshness)


def _alpaca(settings: Settings, symbol: str, *, interval: str, start: datetime,
            end: datetime) -> BarResult:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise RuntimeError("Alpaca credentials are not configured")
    timeframe = "1Day" if interval == "1d" else "5Min"
    response = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        },
        params={
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "adjustment": "all",
            "feed": settings.alpaca_stock_feed,
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json().get("bars", [])
    frame = pd.DataFrame(rows or [])
    if not frame.empty:
        frame = frame.rename(columns={
            "t": "timestamp", "o": "Open", "h": "High", "l": "Low",
            "c": "Close", "v": "Volume",
        })
    return BarResult(_normalise(frame, index="timestamp"), "alpaca", f"Alpaca {settings.alpaca_stock_feed} feed")


def _twelve_data(settings: Settings, symbol: str, *, interval: str, start: datetime,
                 end: datetime) -> BarResult:
    if not settings.twelve_data_api_key:
        raise RuntimeError("TWELVE_DATA_API_KEY is not configured")
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": symbol,
            "interval": "1day" if interval == "1d" else "5min",
            "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
            "outputsize": 5000,
            "timezone": "UTC",
            "adjust": "splits",
            "apikey": settings.twelve_data_api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "error":
        raise RuntimeError(str(payload.get("message", "Twelve Data error")))
    frame = pd.DataFrame(payload.get("values", []) or [])
    if not frame.empty:
        frame = frame.rename(columns={
            "datetime": "timestamp", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
        })
    return BarResult(_normalise(frame, index="timestamp"), "twelve_data", "free-account feed; account terms apply")


def _polygon(settings: Settings, symbol: str, *, interval: str, start: datetime,
             end: datetime) -> BarResult:
    if not settings.polygon_api_key:
        raise RuntimeError("POLYGON_API_KEY is not configured")
    multiplier, timespan = (1, "day") if interval == "1d" else (5, "minute")
    response = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start.date().isoformat()}/{end.date().isoformat()}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": settings.polygon_api_key},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json().get("results", [])
    frame = pd.DataFrame(rows or [])
    if not frame.empty:
        frame["timestamp"] = pd.to_datetime(frame["t"], unit="ms", utc=True)
        frame = frame.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return BarResult(_normalise(frame, index="timestamp"), "polygon", "free plan entitlement / end-of-day limits may apply")


def _alpha_vantage(settings: Settings, symbol: str, *, interval: str, start: datetime,
                   end: datetime) -> BarResult:
    if not settings.alpha_vantage_api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY is not configured")
    params: dict[str, Any] = {"symbol": symbol, "apikey": settings.alpha_vantage_api_key, "outputsize": "full"}
    if interval == "1d":
        params["function"] = "TIME_SERIES_DAILY"
        key = "Time Series (Daily)"
    else:
        params.update(function="TIME_SERIES_INTRADAY", interval="5min")
        key = "Time Series (5min)"
    response = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if "Note" in payload or "Information" in payload:
        raise RuntimeError(str(payload.get("Note") or payload.get("Information")))
    rows = []
    for timestamp, values in (payload.get(key, {}) or {}).items():
        rows.append({
            "timestamp": timestamp,
            "Open": values.get("1. open"),
            "High": values.get("2. high"),
            "Low": values.get("3. low"),
            "Close": values.get("4. close"),
            "Volume": values.get("5. volume", 0),
        })
    frame = _normalise(pd.DataFrame(rows), index="timestamp")
    return BarResult(frame[(frame.index >= start) & (frame.index <= end)], "alpha_vantage", "standard free API; daily quota applies")


Provider = Callable[[Settings, str], BarResult]


def _provider_names(settings: Settings, *, intraday: bool) -> list[str]:
    raw = settings.intraday_provider_order if intraday else settings.daily_provider_order
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _call_provider(name: str, settings: Settings, symbol: str, *, interval: str,
                   start: datetime, end: datetime, period: str) -> BarResult:
    if name == "tradier":
        return _tradier(settings, symbol, interval=interval, start=start, end=end)
    if name == "alpaca":
        return _alpaca(settings, symbol, interval=interval, start=start, end=end)
    if name in {"twelve", "twelvedata", "twelve_data"}:
        return _twelve_data(settings, symbol, interval=interval, start=start, end=end)
    if name == "polygon":
        return _polygon(settings, symbol, interval=interval, start=start, end=end)
    if name in {"alpha", "alphavantage", "alpha_vantage"}:
        return _alpha_vantage(settings, symbol, interval=interval, start=start, end=end)
    if name == "yahoo":
        return _yahoo(symbol, period=period, interval=interval, start=start if interval != "1d" else None, end=end)
    raise RuntimeError(f"Unknown bar provider: {name}")


def fetch_bars(settings: Settings, symbol: str, *, interval: str = "1d", period: str = "1y",
               start: datetime | None = None, end: datetime | None = None) -> BarResult:
    end = end or datetime.now(timezone.utc)
    start = start or (_period_start(period) if interval == "1d" else end - timedelta(days=14))
    failures: list[str] = []
    for name in _provider_names(settings, intraday=interval != "1d"):
        try:
            result = _call_provider(name, settings, symbol, interval=interval, start=start, end=end, period=period)
            if not result.frame.empty:
                return result
            failures.append(f"{name}: empty")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            LOGGER.debug("Bar provider %s failed for %s: %s", name, symbol, exc)
    raise RuntimeError("All bar providers failed: " + " | ".join(failures))


def get_daily_history(settings: Settings, symbol: str, period: str = "1y") -> pd.DataFrame:
    return fetch_bars(settings, symbol, interval="1d", period=period).frame


def get_intraday_history(settings: Settings, symbol: str, start: datetime,
                         end: datetime | None = None) -> BarResult:
    return fetch_bars(settings, symbol, interval="5m", start=start, end=end or datetime.now(timezone.utc), period="1mo")


def configured_bar_sources(settings: Settings) -> list[dict[str, Any]]:
    return [
        {"name": "yahoo", "configured": True, "role": "unofficial fallback"},
        {"name": "tradier", "configured": bool(settings.tradier_token), "role": "official account API"},
        {"name": "alpaca", "configured": bool(settings.alpaca_api_key and settings.alpaca_secret_key), "role": "official account API"},
        {"name": "twelve_data", "configured": bool(settings.twelve_data_api_key), "role": "optional free-account API"},
        {"name": "polygon", "configured": bool(settings.polygon_api_key), "role": "optional free-account API"},
        {"name": "alpha_vantage", "configured": bool(settings.alpha_vantage_api_key), "role": "optional free-account API"},
    ]
