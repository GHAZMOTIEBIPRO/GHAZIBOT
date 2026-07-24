from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .market_bars import get_daily_history
from .settings import Settings

LOGGER = logging.getLogger(__name__)
STANDARD_COLUMNS = [
    "contract_symbol", "symbol", "expiration", "strike", "option_type",
    "bid", "ask", "last", "volume", "open_interest", "iv", "delta",
    "gamma", "theta", "vega", "underlying_price", "updated_at", "source",
    "data_quality", "freshness_label", "aggressor_proxy",
]


def _empty_chain() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def _as_float(value: Any, default: float = np.nan) -> float:
    try:
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return default if value is None or value == "" else int(float(value))
    except (TypeError, ValueError):
        return default


def _to_utc(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        return pd.Timestamp.now(tz="UTC")
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="s", utc=True)
    return pd.to_datetime(value, utc=True, errors="coerce")


def _aggressor_proxy(last: float, bid: float, ask: float) -> str:
    if any(math.isnan(x) for x in (last, bid, ask)) or ask <= bid:
        return "unknown"
    spread = ask - bid
    if last >= ask - 0.15 * spread:
        return "ask"
    if last <= bid + 0.15 * spread:
        return "bid"
    return "mid"


class OptionsProvider(ABC):
    name: str

    @abstractmethod
    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        raise NotImplementedError


class YahooProvider(OptionsProvider):
    name = "yahoo"

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        today = date.today()
        expirations = [
            raw for raw in ticker.options
            if min_dte <= (datetime.strptime(raw, "%Y-%m-%d").date() - today).days <= max_dte
        ][:8]
        if not expirations:
            return _empty_chain()
        hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
        underlying = float(hist["Close"].dropna().iloc[-1]) if not hist.empty else np.nan
        frames: list[pd.DataFrame] = []
        for expiry in expirations:
            try:
                chain = ticker.option_chain(expiry)
            except Exception as exc:
                LOGGER.warning("Yahoo chain failed for %s %s: %s", symbol, expiry, exc)
                continue
            for option_type, raw in (("call", chain.calls), ("put", chain.puts)):
                if raw is None or raw.empty:
                    continue
                df = pd.DataFrame({
                    "contract_symbol": raw["contractSymbol"],
                    "symbol": symbol,
                    "expiration": pd.to_datetime(expiry),
                    "strike": pd.to_numeric(raw["strike"], errors="coerce"),
                    "option_type": option_type,
                    "bid": pd.to_numeric(raw["bid"], errors="coerce"),
                    "ask": pd.to_numeric(raw["ask"], errors="coerce"),
                    "last": pd.to_numeric(raw["lastPrice"], errors="coerce"),
                    "volume": pd.to_numeric(raw["volume"], errors="coerce").fillna(0),
                    "open_interest": pd.to_numeric(raw["openInterest"], errors="coerce").fillna(0),
                    "iv": pd.to_numeric(raw["impliedVolatility"], errors="coerce"),
                    "delta": np.nan,
                    "gamma": np.nan,
                    "theta": np.nan,
                    "vega": np.nan,
                    "underlying_price": underlying,
                    "updated_at": pd.to_datetime(raw["lastTradeDate"], utc=True, errors="coerce"),
                    "source": "yahoo/yfinance",
                    "data_quality": 0.52,
                    "freshness_label": "unofficial / may be delayed",
                })
                df["aggressor_proxy"] = [
                    _aggressor_proxy(l, b, a)
                    for l, b, a in zip(df["last"], df["bid"], df["ask"], strict=False)
                ]
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else _empty_chain()


class MarketDataProvider(OptionsProvider):
    name = "marketdata"
    base_url = "https://api.marketdata.app/v1/options/chain"

    def __init__(self, settings: Settings):
        if not settings.marketdata_token:
            raise ValueError("MARKETDATA_TOKEN is required")
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {settings.marketdata_token}"})

    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        today = date.today()
        params = {
            "from": (today + timedelta(days=min_dte)).isoformat(),
            "to": (today + timedelta(days=max_dte)).isoformat(),
            "strikeLimit": 24,
            "minOpenInterest": max(1, self.settings.min_open_interest // 2),
            "minVolume": max(1, self.settings.min_option_volume // 2),
            "dateformat": "timestamp",
        }
        response = self.session.get(f"{self.base_url}/{symbol}/", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("s") != "ok":
            return _empty_chain()
        mapping = {
            "contract_symbol": "optionSymbol", "symbol": "underlying",
            "expiration": "expiration", "strike": "strike", "option_type": "side",
            "bid": "bid", "ask": "ask", "last": "last", "volume": "volume",
            "open_interest": "openInterest", "iv": "iv", "delta": "delta",
            "gamma": "gamma", "theta": "theta", "vega": "vega",
            "underlying_price": "underlyingPrice", "updated_at": "updated",
        }
        rows = []
        for i in range(len(payload.get("optionSymbol", []))):
            row = {}
            for target, source in mapping.items():
                values = payload.get(source, [])
                row[target] = values[i] if i < len(values) else None
            row["expiration"] = pd.to_datetime(row["expiration"], errors="coerce")
            row["updated_at"] = _to_utc(row["updated_at"])
            row.update(
                source="marketdata.app",
                data_quality=0.72,
                freshness_label="free plan: at least 24h delayed",
            )
            row["aggressor_proxy"] = _aggressor_proxy(
                _as_float(row["last"]), _as_float(row["bid"]), _as_float(row["ask"])
            )
            rows.append(row)
        return pd.DataFrame(rows, columns=STANDARD_COLUMNS)


class TradierProvider(OptionsProvider):
    name = "tradier"

    def __init__(self, settings: Settings):
        if not settings.tradier_token:
            raise ValueError("TRADIER_TOKEN is required")
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.tradier_token}",
            "Accept": "application/json",
        })

    @property
    def quality(self) -> tuple[float, str]:
        if "sandbox" in self.settings.tradier_base_url:
            return 0.65, "Tradier sandbox: delayed; Greeks unavailable"
        return 0.88, "Tradier brokerage feed"

    def _expirations(self, symbol: str) -> list[str]:
        response = self.session.get(
            f"{self.settings.tradier_base_url}/v1/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
            timeout=30,
        )
        response.raise_for_status()
        dates = response.json().get("expirations", {}).get("date", [])
        return [dates] if isinstance(dates, str) else list(dates or [])

    def _underlying(self, symbol: str) -> float:
        response = self.session.get(
            f"{self.settings.tradier_base_url}/v1/markets/quotes",
            params={"symbols": symbol, "greeks": "false"},
            timeout=30,
        )
        response.raise_for_status()
        quote = response.json().get("quotes", {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        return _as_float(quote.get("last"))

    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        today = date.today()
        expirations = [
            raw for raw in self._expirations(symbol)
            if min_dte <= (datetime.strptime(raw, "%Y-%m-%d").date() - today).days <= max_dte
        ][:8]
        if not expirations:
            return _empty_chain()
        underlying = self._underlying(symbol)
        quality, freshness = self.quality
        rows = []
        for expiry in expirations:
            response = self.session.get(
                f"{self.settings.tradier_base_url}/v1/markets/options/chains",
                params={"symbol": symbol, "expiration": expiry, "greeks": "true"},
                timeout=30,
            )
            response.raise_for_status()
            options = response.json().get("options", {}).get("option", [])
            if isinstance(options, dict):
                options = [options]
            for item in options or []:
                greeks = item.get("greeks") or {}
                last, bid, ask = (_as_float(item.get(k)) for k in ("last", "bid", "ask"))
                rows.append({
                    "contract_symbol": item.get("symbol"),
                    "symbol": symbol,
                    "expiration": pd.to_datetime(item.get("expiration_date")),
                    "strike": _as_float(item.get("strike")),
                    "option_type": str(item.get("option_type", "")).lower(),
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "volume": _as_int(item.get("volume")),
                    "open_interest": _as_int(item.get("open_interest")),
                    "iv": _as_float(greeks.get("mid_iv")),
                    "delta": _as_float(greeks.get("delta")),
                    "gamma": _as_float(greeks.get("gamma")),
                    "theta": _as_float(greeks.get("theta")),
                    "vega": _as_float(greeks.get("vega")),
                    "underlying_price": underlying,
                    "updated_at": pd.Timestamp.now(tz="UTC"),
                    "source": "tradier",
                    "data_quality": quality,
                    "freshness_label": freshness,
                    "aggressor_proxy": _aggressor_proxy(last, bid, ask),
                })
        return pd.DataFrame(rows, columns=STANDARD_COLUMNS)


class CompositeOptionsProvider(OptionsProvider):
    """Merge every configured option source by OCC contract symbol.

    The highest-quality row becomes the base record; missing Greeks or quote fields
    are filled from lower-ranked sources. Provider failures are isolated per symbol.
    """

    name = "hybrid"

    def __init__(self, providers: list[OptionsProvider]):
        self.providers = providers

    @staticmethod
    def _merge(frames: list[pd.DataFrame]) -> pd.DataFrame:
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.dropna(subset=["contract_symbol"])
        if combined.empty:
            return _empty_chain()
        combined["contract_symbol"] = combined["contract_symbol"].astype(str)
        combined["data_quality"] = pd.to_numeric(combined["data_quality"], errors="coerce").fillna(0)
        rows: list[pd.Series] = []
        for _, group in combined.sort_values("data_quality", ascending=False).groupby("contract_symbol", sort=False):
            base = group.iloc[0].copy()
            for column in STANDARD_COLUMNS:
                value = base.get(column)
                if pd.isna(value) or value in (None, ""):
                    candidates = group[column].dropna() if column in group else pd.Series(dtype=object)
                    if not candidates.empty:
                        base[column] = candidates.iloc[0]
            sources = list(dict.fromkeys(str(value) for value in group["source"].dropna() if str(value)))
            freshness = list(dict.fromkeys(str(value) for value in group["freshness_label"].dropna() if str(value)))
            base["source"] = " + ".join(sources)
            base["freshness_label"] = " | ".join(freshness)
            rows.append(base)
        return pd.DataFrame(rows, columns=STANDARD_COLUMNS).reset_index(drop=True)

    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for provider in self.providers:
            try:
                frame = provider.get_chain(symbol, min_dte, max_dte)
                if frame is not None and not frame.empty:
                    frames.append(frame)
            except Exception as exc:
                LOGGER.warning("Option source %s failed for %s: %s", provider.name, symbol, exc)
        return self._merge(frames) if frames else _empty_chain()


class AlpacaEnricher:
    url = "https://data.alpaca.markets/v1beta1/options/snapshots"

    def __init__(self, settings: Settings):
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        })

    def enrich(self, chain: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if chain.empty:
            return chain
        snapshots: dict[str, Any] = {}
        page_token = None
        while True:
            params = {"feed": self.settings.alpaca_options_feed, "limit": 1000}
            if page_token:
                params["page_token"] = page_token
            response = self.session.get(f"{self.url}/{symbol}", params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            snapshots.update(payload.get("snapshots", {}))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        out = chain.copy()
        for idx, row in out.iterrows():
            snap = snapshots.get(str(row["contract_symbol"]))
            if not snap:
                continue
            quote = snap.get("latestQuote") or {}
            trade = snap.get("latestTrade") or {}
            greeks = snap.get("greeks") or {}
            bid = _as_float(quote.get("bp"), _as_float(row["bid"]))
            ask = _as_float(quote.get("ap"), _as_float(row["ask"]))
            last = _as_float(trade.get("p"), _as_float(row["last"]))
            out.at[idx, "bid"], out.at[idx, "ask"], out.at[idx, "last"] = bid, ask, last
            out.at[idx, "iv"] = _as_float(snap.get("impliedVolatility"), _as_float(row["iv"]))
            for greek in ("delta", "gamma", "theta", "vega"):
                out.at[idx, greek] = _as_float(greeks.get(greek), _as_float(row[greek]))
            out.at[idx, "updated_at"] = _to_utc(quote.get("t") or trade.get("t"))
            out.at[idx, "source"] = f"{row['source']} + alpaca"
            out.at[idx, "data_quality"] = min(0.95, max(_as_float(row["data_quality"], 0.0), 0.82))
            out.at[idx, "freshness_label"] = f"{row['freshness_label']} | Alpaca {self.settings.alpaca_options_feed}"
            out.at[idx, "aggressor_proxy"] = _aggressor_proxy(last, bid, ask)
        return out


def select_provider(settings: Settings) -> OptionsProvider:
    if settings.provider == "marketdata":
        return MarketDataProvider(settings)
    if settings.provider == "tradier":
        return TradierProvider(settings)
    if settings.provider == "yahoo":
        return YahooProvider(settings)

    providers: list[OptionsProvider] = []
    if settings.tradier_token:
        providers.append(TradierProvider(settings))
    if settings.marketdata_token:
        providers.append(MarketDataProvider(settings))
    providers.append(YahooProvider(settings))
    return CompositeOptionsProvider(providers)


def maybe_enrich_with_alpaca(settings: Settings, chain: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        return chain
    try:
        return AlpacaEnricher(settings).enrich(chain, symbol)
    except Exception as exc:
        LOGGER.warning("Alpaca enrichment failed for %s: %s", symbol, exc)
        return chain


def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    settings = Settings()
    try:
        return get_daily_history(settings, symbol, period=period)
    except Exception as exc:
        LOGGER.warning("Hybrid daily history failed for %s; using Yahoo: %s", symbol, exc)
        data = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data.dropna(how="all")


def load_universe(path: str = "data/universe.txt") -> list[str]:
    with open(path, encoding="utf-8") as handle:
        return [line.strip().upper() for line in handle if line.strip() and not line.startswith("#")]
