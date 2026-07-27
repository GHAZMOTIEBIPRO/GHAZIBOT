from __future__ import annotations

import logging
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Generic, TypeVar
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .advanced_signals import is_standard_occ_contract
from .settings import Settings

LOGGER = logging.getLogger(__name__)
RIYADH_TZ = ZoneInfo("Asia/Riyadh")
T = TypeVar("T")
OHLCV = ["Open", "High", "Low", "Close", "Volume"]
OPTION_COLUMNS = [
    "contract_symbol", "symbol", "expiration", "strike", "option_type",
    "bid", "ask", "last", "volume", "open_interest", "iv", "delta",
    "gamma", "theta", "vega", "underlying_price", "updated_at", "source",
    "data_quality", "freshness_label", "greeks_method", "dte", "spread_pct",
    "standard_contract", "quality_passed", "rejection_reason",
]
_SEC_FORMS = {"4", "SC 13D", "SC 13D/A", "S-1", "S-1/A", "S-3", "S-3/A"}
_OCC_EXPIRY = re.compile(r"^[A-Z]{1,6}(?P<date>\d{6})[CP]\d{8}$")


class DataUnavailableError(RuntimeError):
    """Raised when every configured provider fails or returns unusable data."""

    def __init__(self, operation: str, attempts: list["FetchAttempt"]):
        self.operation = operation
        self.attempts = attempts
        detail = " | ".join(
            f"{item.provider}: {item.error or 'empty response'}" for item in attempts
        )
        super().__init__(f"{operation} failed across all providers: {detail}")


@dataclass(frozen=True)
class FetchAttempt:
    provider: str
    operation: str
    success: bool
    elapsed_ms: int
    rows: int = 0
    status_code: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FetchResult(Generic[T]):
    data: T
    source: str
    freshness: str
    fetched_at: str
    attempts: list[FetchAttempt] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def audit_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "freshness": self.freshness,
            "fetched_at": self.fetched_at,
            "attempts": [item.to_dict() for item in self.attempts],
            "metadata": self.metadata,
        }


class RateLimiter:
    """Thread-safe minimum-interval limiter."""

    def __init__(self, requests_per_second: float):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._interval - (now - self._last_request)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_request = time.monotonic()


def _now_riyadh() -> str:
    return datetime.now(RIYADH_TZ).isoformat()


def _utc_timestamp(value: datetime | date | pd.Timestamp | None) -> pd.Timestamp:
    stamp = pd.Timestamp(value or datetime.now(timezone.utc))
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _safe_float(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: int = 0) -> int:
    number = _safe_float(value)
    return default if math.isnan(number) else int(number)


def _normalise_bars(frame: pd.DataFrame, *, index_column: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=OHLCV)
    out = frame.copy()
    if index_column and index_column in out:
        out.index = pd.to_datetime(out.pop(index_column), utc=True, errors="coerce")
    else:
        out.index = pd.to_datetime(out.index, utc=True, errors="coerce")
    lowered = {str(column).lower(): column for column in out.columns}
    result = pd.DataFrame(index=out.index)
    for target in OHLCV:
        source = lowered.get(target.lower())
        result[target] = (
            pd.to_numeric(out[source], errors="coerce")
            if source is not None else (0.0 if target == "Volume" else np.nan)
        )
    result = result[~result.index.isna()]
    return result.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()


def _option_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OPTION_COLUMNS)
    frame = pd.DataFrame(rows)
    for column in OPTION_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
    return frame[OPTION_COLUMNS]


def _expiry_from_occ(contract: str) -> date | None:
    match = _OCC_EXPIRY.fullmatch(str(contract or "").upper().replace(" ", ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group("date"), "%y%m%d").date()
    except ValueError:
        return None


class DataFetcher:
    """Provider-isolated market/SEC data engine with deterministic fallback."""

    def __init__(self, settings: Settings | None = None, session: requests.Session | None = None):
        self.settings = settings or Settings()
        self.timeout = int(getattr(self.settings, "request_timeout_seconds", 30))
        self.session = session or self._build_session()
        sec_rps = min(10.0, float(getattr(self.settings, "sec_requests_per_second", 8.0)))
        self.sec_limiter = RateLimiter(sec_rps)

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update({"Accept": "application/json"})
        return session

    def _attempt(
        self,
        provider: str,
        operation: str,
        fn: Callable[[], T],
        row_counter: Callable[[T], int] | None = None,
    ) -> tuple[T | None, FetchAttempt]:
        started = time.perf_counter()
        try:
            value = fn()
            rows = row_counter(value) if row_counter else 1
            success = value is not None and rows > 0
            return value, FetchAttempt(
                provider=provider,
                operation=operation,
                success=success,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                rows=rows,
                error=None if success else "empty response",
            )
        except requests.HTTPError as exc:
            response = exc.response
            error = f"HTTP {response.status_code}" if response is not None else str(exc)
            LOGGER.warning("%s provider %s failed: %s", operation, provider, error)
            return None, FetchAttempt(
                provider, operation, False,
                round((time.perf_counter() - started) * 1000),
                status_code=response.status_code if response is not None else None,
                error=error,
            )
        except Exception as exc:
            LOGGER.warning("%s provider %s failed: %s", operation, provider, exc)
            return None, FetchAttempt(
                provider, operation, False,
                round((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        sec: bool = False,
    ) -> Any:
        if sec:
            self.sec_limiter.wait()
        response = self.session.get(
            url, params=params, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def _get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        sec: bool = False,
    ) -> str:
        if sec:
            self.sec_limiter.wait()
        response = self.session.get(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    # ------------------------------- Stock bars -------------------------------

    def fetch_stock_bars(
        self,
        symbol: str,
        *,
        start: datetime | date | None = None,
        end: datetime | date | None = None,
        interval: str = "1d",
        providers: list[str] | None = None,
    ) -> FetchResult[pd.DataFrame]:
        symbol = symbol.strip().upper()
        end_dt = _utc_timestamp(end)
        start_value = start or (end_dt - pd.Timedelta(days=420 if interval == "1d" else 30))
        start_dt = _utc_timestamp(start_value)
        order = providers or [
            item.strip().lower()
            for item in str(getattr(self.settings, "stock_provider_order", "tiingo,finnhub,yahoo")).split(",")
            if item.strip()
        ]
        attempts: list[FetchAttempt] = []
        loaders: dict[str, Callable[[], pd.DataFrame]] = {
            "tiingo": lambda: self._tiingo_bars(symbol, start_dt, end_dt, interval),
            "finnhub": lambda: self._finnhub_bars(symbol, start_dt, end_dt, interval),
            "yahoo": lambda: self._yahoo_bars(symbol, start_dt, end_dt, interval),
            "yfinance": lambda: self._yahoo_bars(symbol, start_dt, end_dt, interval),
        }
        freshness = {
            "tiingo": "Tiingo account entitlement; timestamped provider data",
            "finnhub": "Finnhub account entitlement; timestamped provider data",
            "yahoo": "unofficial fallback; may be delayed",
            "yfinance": "unofficial fallback; may be delayed",
        }
        for provider in order:
            loader = loaders.get(provider)
            if loader is None:
                attempts.append(FetchAttempt(provider, "stock_bars", False, 0, error="unsupported provider"))
                continue
            frame, attempt = self._attempt(provider, "stock_bars", loader, len)
            attempts.append(attempt)
            if attempt.success and isinstance(frame, pd.DataFrame):
                return FetchResult(
                    frame, provider, freshness[provider], _now_riyadh(), attempts,
                    {"symbol": symbol, "interval": interval},
                )
        raise DataUnavailableError(f"stock_bars:{symbol}", attempts)

    def _tiingo_bars(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp, interval: str
    ) -> pd.DataFrame:
        token = getattr(self.settings, "tiingo_api_key", None)
        if not token:
            raise RuntimeError("TIINGO_API_KEY is not configured")
        headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
        if interval == "1d":
            url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
            params = {
                "startDate": start.date().isoformat(),
                "endDate": end.date().isoformat(),
                "resampleFreq": "daily",
            }
        else:
            url = f"https://api.tiingo.com/iex/{symbol}/prices"
            params = {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "resampleFreq": "5min" if interval in {"5m", "5min"} else interval,
                "columns": "date,open,high,low,close,volume",
            }
        payload = self._get_json(url, params=params, headers=headers)
        frame = pd.DataFrame(payload or [])
        if not frame.empty:
            frame = frame.rename(columns={
                "date": "timestamp", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            })
        return _normalise_bars(frame, index_column="timestamp")

    def _finnhub_bars(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp, interval: str
    ) -> pd.DataFrame:
        token = getattr(self.settings, "finnhub_api_key", None)
        if not token:
            raise RuntimeError("FINNHUB_API_KEY is not configured")
        resolution = "D" if interval == "1d" else "5"
        payload = self._get_json(
            "https://api.finnhub.io/api/v1/stock/candle",
            params={
                "symbol": symbol,
                "resolution": resolution,
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
                "token": token,
            },
        )
        if not isinstance(payload, dict) or payload.get("s") != "ok":
            raise RuntimeError(str((payload or {}).get("s", "invalid Finnhub response")))
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(payload.get("t", []), unit="s", utc=True),
            "Open": payload.get("o", []), "High": payload.get("h", []),
            "Low": payload.get("l", []), "Close": payload.get("c", []),
            "Volume": payload.get("v", []),
        })
        return _normalise_bars(frame, index_column="timestamp")

    @staticmethod
    def _yahoo_bars(
        symbol: str, start: pd.Timestamp, end: pd.Timestamp, interval: str
    ) -> pd.DataFrame:
        data = yf.download(
            symbol,
            start=start.to_pydatetime(),
            end=(end + pd.Timedelta(days=1)).to_pydatetime(),
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return _normalise_bars(data)

    # ----------------------------- Option chains ------------------------------

    def fetch_option_chain(
        self,
        symbol: str,
        *,
        min_dte: int | None = None,
        max_dte: int | None = None,
        providers: list[str] | None = None,
        apply_guards: bool = True,
    ) -> FetchResult[pd.DataFrame]:
        symbol = symbol.strip().upper()
        min_days = int(min_dte if min_dte is not None else getattr(self.settings, "min_dte", 14))
        max_days = int(max_dte if max_dte is not None else getattr(self.settings, "max_dte", 60))
        order = providers or [
            item.strip().lower()
            for item in str(getattr(self.settings, "options_provider_order", "tradier,finnhub,yahoo")).split(",")
            if item.strip()
        ]
        attempts: list[FetchAttempt] = []
        loaders: dict[str, Callable[[], pd.DataFrame]] = {
            "tradier": lambda: self._tradier_chain(symbol, min_days, max_days),
            "finnhub": lambda: self._finnhub_chain(symbol, min_days, max_days),
            "yahoo": lambda: self._yahoo_chain(symbol, min_days, max_days),
            "yfinance": lambda: self._yahoo_chain(symbol, min_days, max_days),
        }
        freshness = {
            "tradier": (
                "Tradier sandbox: 15-minute delayed; provider Greeks unavailable"
                if "sandbox" in str(getattr(self.settings, "tradier_base_url", ""))
                else "Tradier brokerage market data"
            ),
            "finnhub": "Finnhub account entitlement",
            "yahoo": "unofficial fallback; may be delayed",
            "yfinance": "unofficial fallback; may be delayed",
        }
        for provider in order:
            loader = loaders.get(provider)
            if loader is None:
                attempts.append(FetchAttempt(provider, "option_chain", False, 0, error="unsupported provider"))
                continue
            frame, attempt = self._attempt(provider, "option_chain", loader, len)
            attempts.append(attempt)
            if not attempt.success or not isinstance(frame, pd.DataFrame):
                continue
            frame = self._fill_missing_greeks(frame)
            if apply_guards:
                frame, _ = self.apply_option_quality_guards(frame, symbol)
            if frame.empty:
                attempts[-1] = FetchAttempt(
                    provider, "option_chain", False, attempt.elapsed_ms,
                    rows=0, error="all contracts rejected by quality guards",
                )
                continue
            return FetchResult(
                frame.reset_index(drop=True), provider, freshness[provider],
                _now_riyadh(), attempts,
                {"symbol": symbol, "min_dte": min_days, "max_dte": max_days},
            )
        raise DataUnavailableError(f"option_chain:{symbol}", attempts)

    def _tradier_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        token = getattr(self.settings, "tradier_token", None)
        if not token:
            raise RuntimeError("TRADIER_TOKEN is not configured")
        base = str(getattr(self.settings, "tradier_base_url", "https://sandbox.tradier.com")).rstrip("/")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        expiry_payload = self._get_json(
            f"{base}/v1/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
            headers=headers,
        )
        dates = (expiry_payload.get("expirations") or {}).get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        today = date.today()
        expirations = [
            raw for raw in dates or []
            if min_dte <= (datetime.strptime(raw, "%Y-%m-%d").date() - today).days <= max_dte
        ][:10]
        quote_payload = self._get_json(
            f"{base}/v1/markets/quotes",
            params={"symbols": symbol, "greeks": "false"},
            headers=headers,
        )
        quote = (quote_payload.get("quotes") or {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0] if quote else {}
        underlying_price = _safe_float(quote.get("last") or quote.get("close"))

        rows: list[dict[str, Any]] = []
        for expiry in expirations:
            payload = self._get_json(
                f"{base}/v1/markets/options/chains",
                params={"symbol": symbol, "expiration": expiry, "greeks": "true"},
                headers=headers,
            )
            options = (payload.get("options") or {}).get("option", [])
            if isinstance(options, dict):
                options = [options]
            for item in options or []:
                greek = item.get("greeks") or {}
                rows.append(self._build_option_row(
                    symbol=symbol,
                    contract=item.get("symbol"),
                    expiry=item.get("expiration_date") or expiry,
                    strike=item.get("strike"),
                    side=item.get("option_type"),
                    bid=item.get("bid"), ask=item.get("ask"), last=item.get("last"),
                    volume=item.get("volume"), open_interest=item.get("open_interest"),
                    iv=greek.get("mid_iv") or greek.get("smv_vol"),
                    delta=greek.get("delta"), gamma=greek.get("gamma"),
                    theta=greek.get("theta"), vega=greek.get("vega"),
                    underlying=item.get("underlying_price") or underlying_price,
                    updated_at=item.get("trade_date"),
                    source="tradier",
                    data_quality=0.66 if "sandbox" in base else 0.90,
                    freshness="sandbox delayed" if "sandbox" in base else "brokerage feed",
                ))
        return _option_frame(rows)

    def _finnhub_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        token = getattr(self.settings, "finnhub_api_key", None)
        if not token:
            raise RuntimeError("FINNHUB_API_KEY is not configured")
        payload = self._get_json(
            "https://api.finnhub.io/api/v1/stock/option-chain",
            params={"symbol": symbol, "token": token},
        )
        nodes = []
        if isinstance(payload, dict):
            for key in ("data", "optionChain", "chains"):
                value = payload.get(key)
                if isinstance(value, list):
                    nodes = value
                    break
            if not nodes and isinstance(payload.get("options"), (list, dict)):
                nodes = [payload]
        elif isinstance(payload, list):
            nodes = payload
        today = date.today()
        rows: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            expiry = node.get("expirationDate") or node.get("expiration") or node.get("date")
            expiry_date = pd.to_datetime(expiry, errors="coerce")
            if pd.isna(expiry_date):
                continue
            dte = (expiry_date.date() - today).days
            if not min_dte <= dte <= max_dte:
                continue
            groups = node.get("options") or node
            for side, aliases in (("call", ("CALL", "call", "calls")), ("put", ("PUT", "put", "puts"))):
                contracts: list[Any] = []
                for alias in aliases:
                    value = groups.get(alias) if isinstance(groups, dict) else None
                    if isinstance(value, list):
                        contracts = value
                        break
                for item in contracts:
                    if not isinstance(item, dict):
                        continue
                    greek = item.get("greeks") or {}
                    rows.append(self._build_option_row(
                        symbol=symbol,
                        contract=item.get("contractName") or item.get("contractSymbol") or item.get("symbol"),
                        expiry=expiry,
                        strike=item.get("strike"),
                        side=side,
                        bid=item.get("bid"), ask=item.get("ask"),
                        last=item.get("lastPrice") or item.get("last"),
                        volume=item.get("volume"), open_interest=item.get("openInterest"),
                        iv=item.get("impliedVolatility") or item.get("iv"),
                        delta=greek.get("delta") or item.get("delta"),
                        gamma=greek.get("gamma") or item.get("gamma"),
                        theta=greek.get("theta") or item.get("theta"),
                        vega=greek.get("vega") or item.get("vega"),
                        underlying=node.get("underlyingPrice") or item.get("underlyingPrice"),
                        updated_at=item.get("lastTradeDate"),
                        source="finnhub",
                        data_quality=0.78,
                        freshness="account entitlement",
                    ))
        return _option_frame(rows)

    def _yahoo_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        today = date.today()
        expirations = [
            raw for raw in ticker.options
            if min_dte <= (datetime.strptime(raw, "%Y-%m-%d").date() - today).days <= max_dte
        ][:10]
        history = ticker.history(period="5d", interval="1d", auto_adjust=False)
        underlying = float(history["Close"].dropna().iloc[-1]) if not history.empty else np.nan
        rows: list[dict[str, Any]] = []
        for expiry in expirations:
            chain = ticker.option_chain(expiry)
            for side, frame in (("call", chain.calls), ("put", chain.puts)):
                if frame is None or frame.empty:
                    continue
                for _, item in frame.iterrows():
                    rows.append(self._build_option_row(
                        symbol=symbol, contract=item.get("contractSymbol"),
                        expiry=expiry, strike=item.get("strike"), side=side,
                        bid=item.get("bid"), ask=item.get("ask"),
                        last=item.get("lastPrice"), volume=item.get("volume"),
                        open_interest=item.get("openInterest"),
                        iv=item.get("impliedVolatility"),
                        delta=np.nan, gamma=np.nan, theta=np.nan, vega=np.nan,
                        underlying=underlying, updated_at=item.get("lastTradeDate"),
                        source="yahoo/yfinance", data_quality=0.52,
                        freshness="unofficial / may be delayed",
                    ))
        return _option_frame(rows)

    @staticmethod
    def _build_option_row(**values: Any) -> dict[str, Any]:
        expiry = pd.to_datetime(values.get("expiry"), errors="coerce")
        dte = (expiry.date() - date.today()).days if not pd.isna(expiry) else np.nan
        return {
            "contract_symbol": str(values.get("contract") or "").upper().replace(" ", ""),
            "symbol": str(values.get("symbol") or "").upper(),
            "expiration": expiry,
            "strike": _safe_float(values.get("strike")),
            "option_type": str(values.get("side") or "").lower(),
            "bid": _safe_float(values.get("bid")), "ask": _safe_float(values.get("ask")),
            "last": _safe_float(values.get("last")),
            "volume": _safe_int(values.get("volume")),
            "open_interest": _safe_int(values.get("open_interest")),
            "iv": _safe_float(values.get("iv")), "delta": _safe_float(values.get("delta")),
            "gamma": _safe_float(values.get("gamma")), "theta": _safe_float(values.get("theta")),
            "vega": _safe_float(values.get("vega")),
            "underlying_price": _safe_float(values.get("underlying")),
            "updated_at": pd.to_datetime(values.get("updated_at"), utc=True, errors="coerce"),
            "source": values.get("source"), "data_quality": values.get("data_quality"),
            "freshness_label": values.get("freshness"), "greeks_method": "provider",
            "dte": dte, "spread_pct": np.nan, "standard_contract": False,
            "quality_passed": False, "rejection_reason": "",
        }

    def _fill_missing_greeks(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        rate = float(getattr(self.settings, "risk_free_rate", 0.043))
        for idx, row in out.iterrows():
            missing = any(pd.isna(row.get(key)) for key in ("delta", "gamma", "theta", "vega"))
            if not missing:
                continue
            spot = _safe_float(row.get("underlying_price"))
            strike = _safe_float(row.get("strike"))
            iv = _safe_float(row.get("iv"))
            dte = _safe_float(row.get("dte"))
            if any(math.isnan(value) or value <= 0 for value in (spot, strike, iv, dte)):
                continue
            greek = self.black_scholes_greeks(
                spot, strike, dte / 365.0, rate, iv,
                str(row.get("option_type", "call")).lower(),
            )
            for key, value in greek.items():
                if pd.isna(row.get(key)):
                    out.at[idx, key] = value
            out.at[idx, "greeks_method"] = "black_scholes_modeled"
            out.at[idx, "data_quality"] = min(_safe_float(row.get("data_quality"), 0.0), 0.70)
        return out

    @staticmethod
    def black_scholes_greeks(
        spot: float, strike: float, years: float, rate: float, volatility: float, side: str
    ) -> dict[str, float]:
        if min(spot, strike, years, volatility) <= 0:
            raise ValueError("Black-Scholes inputs must be positive")
        root_t = math.sqrt(years)
        d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * years) / (volatility * root_t)
        d2 = d1 - volatility * root_t
        cdf = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        pdf = lambda x: math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
        is_call = side == "call"
        delta = cdf(d1) if is_call else cdf(d1) - 1.0
        gamma = pdf(d1) / (spot * volatility * root_t)
        theta_year = (
            -(spot * pdf(d1) * volatility) / (2.0 * root_t)
            - rate * strike * math.exp(-rate * years) * cdf(d2)
            if is_call else
            -(spot * pdf(d1) * volatility) / (2.0 * root_t)
            + rate * strike * math.exp(-rate * years) * cdf(-d2)
        )
        vega = spot * pdf(d1) * root_t / 100.0
        return {
            "delta": round(delta, 8), "gamma": round(gamma, 8),
            "theta": round(theta_year / 365.0, 8), "vega": round(vega, 8),
        }

    def apply_option_quality_guards(
        self, frame: pd.DataFrame, underlying: str
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        out = frame.copy()
        for column in ("bid", "ask", "delta", "dte"):
            out[column] = pd.to_numeric(out.get(column), errors="coerce")
        out["spread_pct"] = ((out["ask"] - out["bid"]) / out["ask"].replace(0, np.nan)).round(8)
        out["standard_contract"] = [
            is_standard_occ_contract(contract, underlying)
            for contract in out.get("contract_symbol", pd.Series(dtype=str))
        ]
        max_spread = float(getattr(self.settings, "max_spread_pct", 0.15))
        min_delta = float(getattr(self.settings, "min_abs_delta", 0.30))
        max_delta = float(getattr(self.settings, "max_abs_delta", 0.60))
        min_dte = int(getattr(self.settings, "min_dte", 14))
        max_dte = int(getattr(self.settings, "max_dte", 60))

        def rejection(row: pd.Series) -> str:
            if not bool(row.get("standard_contract")):
                return "adjusted_or_nonstandard_contract"
            bid, ask = row.get("bid"), row.get("ask")
            if pd.isna(bid) or pd.isna(ask) or bid <= 0 or ask <= bid:
                return "invalid_bid_ask"
            if pd.isna(row.get("spread_pct")) or float(row["spread_pct"]) > max_spread + 1e-12:
                return "spread_above_15pct"
            if pd.isna(row.get("delta")):
                return "missing_delta"
            if not min_delta <= abs(float(row["delta"])) <= max_delta:
                return "delta_outside_030_060"
            if pd.isna(row.get("dte")) or not min_dte <= int(row["dte"]) <= max_dte:
                return "dte_outside_14_60"
            return ""

        out["rejection_reason"] = out.apply(rejection, axis=1)
        out["quality_passed"] = out["rejection_reason"].eq("")
        accepted = out[out["quality_passed"]].copy()
        rejected = out[~out["quality_passed"]].copy()
        return accepted, rejected

    # ---------------------------- Option history ------------------------------

    def fetch_option_history(
        self,
        contract_symbol: str,
        *,
        start: datetime | date,
        end: datetime | date | None = None,
        interval: str = "1d",
    ) -> FetchResult[pd.DataFrame]:
        contract = contract_symbol.upper().replace(" ", "")
        end_dt = _utc_timestamp(end)
        start_dt = _utc_timestamp(start)
        attempts: list[FetchAttempt] = []

        def tradier() -> pd.DataFrame:
            token = getattr(self.settings, "tradier_token", None)
            if not token:
                raise RuntimeError("TRADIER_TOKEN is not configured")
            base = str(getattr(self.settings, "tradier_base_url", "https://sandbox.tradier.com")).rstrip("/")
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if interval == "1d":
                payload = self._get_json(
                    f"{base}/v1/markets/history",
                    params={
                        "symbol": contract, "interval": "daily",
                        "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat(),
                    },
                    headers=headers,
                )
                rows = (payload.get("history") or {}).get("day", [])
                timestamp = "date"
            else:
                payload = self._get_json(
                    f"{base}/v1/markets/timesales",
                    params={
                        "symbol": contract, "interval": "5min",
                        "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                        "end": end_dt.strftime("%Y-%m-%d %H:%M"),
                        "session_filter": "open",
                    },
                    headers=headers,
                )
                rows = (payload.get("series") or {}).get("data", [])
                timestamp = "time"
            if isinstance(rows, dict):
                rows = [rows]
            frame = pd.DataFrame(rows or [])
            if not frame.empty:
                frame = frame.rename(columns={
                    timestamp: "timestamp", "open": "Open", "high": "High",
                    "low": "Low", "close": "Close", "volume": "Volume",
                })
            return _normalise_bars(frame, index_column="timestamp")

        frame, attempt = self._attempt("tradier", "option_history", tradier, len)
        attempts.append(attempt)
        if attempt.success and isinstance(frame, pd.DataFrame):
            return FetchResult(
                frame, "tradier",
                "sandbox delayed" if "sandbox" in str(getattr(self.settings, "tradier_base_url", "")) else "brokerage feed",
                _now_riyadh(), attempts,
                {"contract_symbol": contract, "interval": interval},
            )
        raise DataUnavailableError(f"option_history:{contract}", attempts)

    # ------------------------------- SEC EDGAR -------------------------------

    def _sec_headers(self) -> dict[str, str]:
        return {
            "User-Agent": str(getattr(self.settings, "sec_user_agent", "GHAZI Market Radar contact@example.com")),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }

    def search_sec_attention(
        self,
        query: str,
        *,
        start_date: date,
        end_date: date,
        forms: tuple[str, ...] = ("4", "8-K", "SC 13D"),
        max_results: int = 300,
    ) -> FetchResult[list[dict[str, Any]]]:
        attempts: list[FetchAttempt] = []

        def load() -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            offset = 0
            while offset < max_results:
                payload = self._get_json(
                    "https://efts.sec.gov/LATEST/search-index",
                    params={
                        "q": query, "dateRange": "custom",
                        "startdt": start_date.isoformat(), "enddt": end_date.isoformat(),
                        "forms": ",".join(forms), "from": offset,
                    },
                    headers=self._sec_headers(), sec=True,
                )
                hits = ((payload.get("hits") or {}).get("hits") or [])
                if not hits:
                    break
                rows.extend(hit for hit in hits if isinstance(hit, dict))
                if len(hits) < 100:
                    break
                offset += 100
            return rows[:max_results]

        rows, attempt = self._attempt("sec_efts", "sec_attention_search", load, len)
        attempts.append(attempt)
        if attempt.success and isinstance(rows, list):
            return FetchResult(
                rows, "SEC EDGAR EFTS", "official filing index",
                _now_riyadh(), attempts,
                {"query": query, "forms": list(forms)},
            )
        raise DataUnavailableError("sec_attention_search", attempts)

    def fetch_sec_filings(
        self,
        cik: str | int,
        *,
        forms: set[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        parse_form4: bool = True,
        max_documents: int = 40,
    ) -> FetchResult[list[dict[str, Any]]]:
        cik10 = str(cik).strip().zfill(10)
        wanted = {item.upper() for item in (forms or _SEC_FORMS)}
        start_date = start_date or (date.today() - timedelta(days=90))
        end_date = end_date or date.today()
        attempts: list[FetchAttempt] = []

        def load() -> list[dict[str, Any]]:
            submissions = self._get_json(
                f"https://data.sec.gov/submissions/CIK{cik10}.json",
                headers=self._sec_headers(), sec=True,
            )
            recent = (submissions.get("filings") or {}).get("recent") or {}
            columns = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
            size = max((len(recent.get(column, [])) for column in columns), default=0)
            rows: list[dict[str, Any]] = []
            for idx in range(size):
                row = {
                    column: recent.get(column, [None] * size)[idx]
                    if idx < len(recent.get(column, [])) else None
                    for column in columns
                }
                filing_date = pd.to_datetime(row["filingDate"], errors="coerce")
                if pd.isna(filing_date):
                    continue
                if not start_date <= filing_date.date() <= end_date:
                    continue
                form = str(row["form"] or "").upper()
                if form not in wanted:
                    continue
                accession = str(row["accessionNumber"] or "")
                folder = accession.replace("-", "")
                primary = str(row["primaryDocument"] or "")
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik10)}/{folder}/{primary}"
                filing = {
                    "cik": cik10, "company": submissions.get("name"),
                    "ticker": (submissions.get("tickers") or [""])[0],
                    "form": form, "filing_date": filing_date.date().isoformat(),
                    "report_date": row.get("reportDate"), "accession": accession,
                    "primary_document": primary, "url": url,
                }
                if parse_form4 and form == "4" and primary.lower().endswith((".xml", ".txt")):
                    filing["transactions"] = self._parse_form4_document(url)
                rows.append(filing)
                if len(rows) >= max_documents:
                    break
            return rows

        rows, attempt = self._attempt("sec_submissions", "sec_filings", load, len)
        attempts.append(attempt)
        if attempt.success and isinstance(rows, list):
            return FetchResult(
                rows, "SEC EDGAR submissions", "official near-real-time filings",
                _now_riyadh(), attempts,
                {"cik": cik10, "forms": sorted(wanted)},
            )
        raise DataUnavailableError(f"sec_filings:{cik10}", attempts)

    def _parse_form4_document(self, url: str) -> list[dict[str, Any]]:
        raw = self._get_text(url, headers=self._sec_headers(), sec=True)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return []

        def local(node: ET.Element) -> str:
            return node.tag.rsplit("}", 1)[-1]

        def nested_text(parent: ET.Element, name: str) -> str:
            for node in parent.iter():
                if local(node) == name:
                    for child in node.iter():
                        if local(child) == "value" and child.text:
                            return child.text.strip()
                    if node.text:
                        return node.text.strip()
            return ""

        transactions: list[dict[str, Any]] = []
        for txn in root.iter():
            if local(txn) != "nonDerivativeTransaction":
                continue
            code = nested_text(txn, "transactionCode").upper()
            direct = nested_text(txn, "directOrIndirectOwnership").upper()
            if code not in {"P", "S"} or direct != "D":
                continue
            shares = _safe_float(nested_text(txn, "transactionShares"))
            price = _safe_float(nested_text(txn, "transactionPricePerShare"))
            transactions.append({
                "transaction_code": code,
                "transaction_date": nested_text(txn, "transactionDate"),
                "shares": None if math.isnan(shares) else shares,
                "price_per_share": None if math.isnan(price) else price,
                "transaction_value": (
                    round(shares * price, 2)
                    if not math.isnan(shares) and not math.isnan(price) else None
                ),
                "acquired_disposed": nested_text(txn, "transactionAcquiredDisposedCode"),
                "ownership": direct,
            })
        return transactions

    # ---------------------------------- FRED ----------------------------------

    def fetch_fred_series(self, series_id: str, *, limit: int = 10) -> FetchResult[pd.DataFrame]:
        key = getattr(self.settings, "fred_api_key", None)
        if not key:
            raise DataUnavailableError(
                f"fred:{series_id}",
                [FetchAttempt("fred", "fred_series", False, 0, error="FRED_API_KEY is not configured")],
            )
        attempts: list[FetchAttempt] = []

        def load() -> pd.DataFrame:
            payload = self._get_json(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": limit,
                },
            )
            frame = pd.DataFrame(payload.get("observations", []) or [])
            if not frame.empty:
                frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce")
                frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
                frame = frame.dropna(subset=["date", "value"]).set_index("date").sort_index()
            return frame

        frame, attempt = self._attempt("fred", "fred_series", load, len)
        attempts.append(attempt)
        if attempt.success and isinstance(frame, pd.DataFrame):
            return FetchResult(
                frame, "FRED", "official daily series",
                _now_riyadh(), attempts, {"series_id": series_id},
            )
        raise DataUnavailableError(f"fred:{series_id}", attempts)
