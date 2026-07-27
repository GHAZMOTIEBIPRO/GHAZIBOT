from __future__ import annotations

import atexit
import json
import math
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import hybrid_fetcher, market_bars, providers as legacy_providers
from .hybrid_fetcher import DataUnavailableError, FetchAttempt, FetchResult

_ORIGINAL_STOCK_FETCH = hybrid_fetcher.DataFetcher.fetch_stock_bars
_ORIGINAL_OPTION_FETCH = hybrid_fetcher.DataFetcher.fetch_option_chain
_INSTALLED = False
_AUDIT_LOCK = threading.Lock()
_SOURCE_AUDIT: dict[str, Any] = {"stocks": {}, "options": {}}
_AUDIT_PATH = Path("data/live/source_audit.json")


def _normalise_name(value: str) -> str:
    name = str(value or "").strip().lower()
    aliases = {
        "yfinance": "yahoo",
        "twelve": "twelve_data",
        "twelvedata": "twelve_data",
        "alpha": "alpha_vantage",
        "alphavantage": "alpha_vantage",
    }
    return aliases.get(name, name)


def _unique_names(*raw_values: str) -> list[str]:
    result: list[str] = []
    for raw in raw_values:
        for item in str(raw or "").split(","):
            name = _normalise_name(item)
            if name and name not in result:
                result.append(name)
    return result


def _record_audit(section: str, key: str, value: dict[str, Any]) -> None:
    with _AUDIT_LOCK:
        _SOURCE_AUDIT.setdefault(section, {})[key] = value


def _write_audit() -> None:
    with _AUDIT_LOCK:
        payload = json.loads(json.dumps(_SOURCE_AUDIT, default=str))
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _AUDIT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(_AUDIT_PATH)


def _as_utc(value: datetime | date | pd.Timestamp | None) -> datetime:
    stamp = pd.Timestamp(value or datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.to_pydatetime()


def _latest_close(frame: pd.DataFrame) -> float | None:
    if frame is None or frame.empty or "Close" not in frame:
        return None
    series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if series.empty:
        return None
    value = float(series.iloc[-1])
    return value if math.isfinite(value) else None


def _consensus_metadata(successes: list[tuple[str, pd.DataFrame, str]]) -> dict[str, Any]:
    closes = {
        name: value
        for name, frame, _ in successes
        if (value := _latest_close(frame)) is not None
    }
    values = list(closes.values())
    dispersion = None
    if len(values) >= 2:
        median = float(np.median(values))
        if median:
            dispersion = max(abs(value - median) for value in values) / abs(median)
    return {
        "successful_sources": [name for name, _, _ in successes],
        "source_count": len(successes),
        "latest_close_by_source": closes,
        "latest_close_dispersion_pct": (
            round(float(dispersion) * 100.0, 4) if dispersion is not None else None
        ),
        "cross_source_confirmed": bool(
            len(successes) >= 2 and dispersion is not None and dispersion <= 0.015
        ),
    }


def _multi_stock_fetch(
    self: hybrid_fetcher.DataFetcher,
    symbol: str,
    *,
    start: datetime | date | None = None,
    end: datetime | date | None = None,
    interval: str = "1d",
    providers: list[str] | None = None,
) -> FetchResult[pd.DataFrame]:
    symbol = str(symbol).strip().upper()
    order = providers or _unique_names(
        getattr(self.settings, "stock_provider_order", ""),
        (
            getattr(self.settings, "daily_provider_order", "")
            if interval == "1d"
            else getattr(self.settings, "intraday_provider_order", "")
        ),
    )
    if "yahoo" not in order:
        order.append("yahoo")

    end_dt = _as_utc(end)
    start_dt = _as_utc(
        start
        or (
            pd.Timestamp(end_dt) - pd.Timedelta(days=420 if interval == "1d" else 30)
        )
    )
    successes: list[tuple[str, pd.DataFrame, str]] = []
    attempts: list[FetchAttempt] = []

    for provider in order:
        provider = _normalise_name(provider)
        try:
            if provider in {"tiingo", "finnhub", "yahoo"}:
                result = _ORIGINAL_STOCK_FETCH(
                    self,
                    symbol,
                    start=start_dt,
                    end=end_dt,
                    interval=interval,
                    providers=[provider],
                )
                attempts.extend(result.attempts)
                if not result.data.empty:
                    successes.append((provider, result.data, result.freshness))
                continue

            result = market_bars._call_provider(
                provider,
                self.settings,
                symbol,
                interval=interval,
                start=start_dt,
                end=end_dt,
                period="1y" if interval == "1d" else "1mo",
            )
            frame = result.frame
            attempts.append(
                FetchAttempt(
                    provider=provider,
                    operation="stock_bars",
                    success=not frame.empty,
                    elapsed_ms=0,
                    rows=len(frame),
                    error=None if not frame.empty else "empty response",
                )
            )
            if not frame.empty:
                successes.append((provider, frame, result.freshness))
        except DataUnavailableError as exc:
            attempts.extend(exc.attempts)
        except Exception as exc:
            attempts.append(
                FetchAttempt(
                    provider=provider,
                    operation="stock_bars",
                    success=False,
                    elapsed_ms=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    if not successes:
        raise DataUnavailableError(f"stock_bars:{symbol}", attempts)

    metadata = _consensus_metadata(successes)
    base_name, base_frame, base_freshness = successes[0]
    result = FetchResult(
        data=base_frame,
        source=base_name,
        freshness=(
            f"multi-source validation ({metadata['source_count']} sources); "
            f"base={base_name}; {base_freshness}"
        ),
        fetched_at=hybrid_fetcher._now_riyadh(),
        attempts=attempts,
        metadata={"symbol": symbol, "interval": interval, **metadata},
    )
    _record_audit("stocks", symbol, result.audit_dict())
    return result


def _merge_option_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=hybrid_fetcher.OPTION_COLUMNS)
    return legacy_providers.CompositeOptionsProvider._merge(frames)


def _multi_option_fetch(
    self: hybrid_fetcher.DataFetcher,
    symbol: str,
    *,
    min_dte: int | None = None,
    max_dte: int | None = None,
    providers: list[str] | None = None,
    apply_guards: bool = True,
) -> FetchResult[pd.DataFrame]:
    symbol = str(symbol).strip().upper()
    order = providers or _unique_names(
        getattr(self.settings, "options_provider_order", "")
    )
    if getattr(self.settings, "marketdata_token", None) and "marketdata" not in order:
        insert_at = order.index("yahoo") if "yahoo" in order else len(order)
        order.insert(insert_at, "marketdata")
    if "yahoo" not in order:
        order.append("yahoo")

    min_days = int(
        min_dte if min_dte is not None else getattr(self.settings, "min_dte", 14)
    )
    max_days = int(
        max_dte if max_dte is not None else getattr(self.settings, "max_dte", 60)
    )
    frames: list[pd.DataFrame] = []
    attempts: list[FetchAttempt] = []
    successful_sources: list[str] = []

    for provider in order:
        provider = _normalise_name(provider)
        try:
            if provider in {"tradier", "finnhub", "yahoo"}:
                result = _ORIGINAL_OPTION_FETCH(
                    self,
                    symbol,
                    min_dte=min_days,
                    max_dte=max_days,
                    providers=[provider],
                    apply_guards=False,
                )
                attempts.extend(result.attempts)
                if not result.data.empty:
                    frames.append(result.data)
                    successful_sources.append(provider)
                continue
            if provider == "marketdata":
                frame, attempt = self._attempt(
                    provider,
                    "option_chain",
                    lambda: legacy_providers.MarketDataProvider(self.settings).get_chain(
                        symbol, min_days, max_days
                    ),
                    len,
                )
                attempts.append(attempt)
                if attempt.success and isinstance(frame, pd.DataFrame):
                    frames.append(frame)
                    successful_sources.append(provider)
                continue
            attempts.append(
                FetchAttempt(
                    provider=provider,
                    operation="option_chain",
                    success=False,
                    elapsed_ms=0,
                    error="provider not integrated for option chains",
                )
            )
        except DataUnavailableError as exc:
            attempts.extend(exc.attempts)
        except Exception as exc:
            attempts.append(
                FetchAttempt(
                    provider=provider,
                    operation="option_chain",
                    success=False,
                    elapsed_ms=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    if not frames:
        raise DataUnavailableError(f"option_chain:{symbol}", attempts)

    merged = _merge_option_frames(frames)
    if getattr(self.settings, "alpaca_api_key", None) and getattr(
        self.settings, "alpaca_secret_key", None
    ):
        before_sources = set(merged.get("source", pd.Series(dtype=str)).astype(str))
        merged = legacy_providers.maybe_enrich_with_alpaca(
            self.settings, merged, symbol
        )
        after_sources = set(merged.get("source", pd.Series(dtype=str)).astype(str))
        if after_sources != before_sources or any("alpaca" in value for value in after_sources):
            successful_sources.append("alpaca")
            attempts.append(
                FetchAttempt(
                    provider="alpaca",
                    operation="option_enrichment",
                    success=True,
                    elapsed_ms=0,
                    rows=len(merged),
                )
            )

    if apply_guards:
        merged, _ = self.apply_option_quality_guards(merged, symbol)
    if merged.empty:
        raise DataUnavailableError(f"option_chain:{symbol}", attempts)

    successful_sources = list(dict.fromkeys(successful_sources))
    metadata = {
        "symbol": symbol,
        "min_dte": min_days,
        "max_dte": max_days,
        "successful_sources": successful_sources,
        "source_count": len(successful_sources),
        "cross_source_confirmed": len(successful_sources) >= 2,
        "contracts_after_merge": len(merged),
    }
    result = FetchResult(
        data=merged.reset_index(drop=True),
        source="multi-source" if len(successful_sources) >= 2 else successful_sources[0],
        freshness=" | ".join(
            str(value)
            for value in merged.get("freshness_label", pd.Series(dtype=str))
            .dropna()
            .astype(str)
            .unique()[:4]
        ),
        fetched_at=hybrid_fetcher._now_riyadh(),
        attempts=attempts,
        metadata=metadata,
    )
    _record_audit("options", symbol, result.audit_dict())
    return result


def _consensus_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    fetcher = hybrid_fetcher.DataFetcher()
    return fetcher.fetch_stock_bars(symbol, interval="1d").data


def install_multi_source_fetching() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    hybrid_fetcher.DataFetcher.fetch_stock_bars = _multi_stock_fetch
    hybrid_fetcher.DataFetcher.fetch_option_chain = _multi_option_fetch
    legacy_providers.get_price_history = _consensus_price_history
    _INSTALLED = True


atexit.register(_write_audit)
