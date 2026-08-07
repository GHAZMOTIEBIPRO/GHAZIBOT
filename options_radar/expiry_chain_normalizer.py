from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from . import hybrid_fetcher
from .expiry_identity import classify_expiry
from .hybrid_fetcher import FetchResult

_ORIGINAL_OPTION_FETCH = hybrid_fetcher.DataFetcher.fetch_option_chain
_INSTALLED = False

_LICENSED_SOURCE_HINTS = (
    "tradier",
    "marketdata",
    "alpaca",
    "finnhub",
    "polygon",
    "opra",
    "cboe",
)


def _number(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _datetime_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return pd.to_datetime(frame[name], utc=True, errors="coerce")


def _quote_provenance(source: Any) -> str:
    text = str(source or "").lower()
    if any(hint in text for hint in _LICENSED_SOURCE_HINTS):
        return "SOURCE_LICENSED"
    if "yahoo" in text or "yfinance" in text:
        return "SOURCE_FALLBACK"
    return "UNVERIFIED"


def _apply_expiry_identity(out: pd.DataFrame) -> pd.DataFrame:
    identities = [classify_expiry(row) for row in out.to_dict(orient="records")]
    if not identities:
        return out
    identity_frame = pd.DataFrame([identity.to_dict() for identity in identities], index=out.index)
    for column in identity_frame.columns:
        out[column] = identity_frame[column]
    out["dte"] = out["calendar_dte"]
    return out


def normalize_expiry_chain(
    frame: pd.DataFrame,
    fetcher: hybrid_fetcher.DataFetcher,
) -> pd.DataFrame:
    """Normalize DTE, expiry identity, provenance, spreads, and missing Greeks.

    Expiry family is deliberately independent from DTE. Provider series metadata
    wins when present; product/calendar inference is a labelled fallback. Missing
    Greeks may be estimated with the existing Black-Scholes screening model, but
    modeled values remain explicitly labelled and cannot masquerade as live
    provider Greeks.
    """

    if frame is None or frame.empty:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    out = frame.copy()
    expiration = _datetime_column(out, "expiration")
    out["expiration"] = expiration
    today_utc = pd.Timestamp(datetime.now(timezone.utc)).normalize()
    computed_dte = (expiration.dt.normalize() - today_utc).dt.days
    existing_dte = _numeric_column(out, "dte")
    out["dte"] = existing_dte.fillna(computed_dte)

    for column in (
        "strike",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "underlying_price",
    ):
        out[column] = _numeric_column(out, column)

    computed_spread = (out["ask"] - out["bid"]) / out["ask"].replace(0, np.nan)
    existing_spread = _numeric_column(out, "spread_pct")
    out["spread_pct"] = existing_spread.fillna(computed_spread)

    if "greeks_method" not in out:
        out["greeks_method"] = "provider"

    missing_delta = out["delta"].isna()
    for idx, row in out.loc[missing_delta].iterrows():
        spot = _number(row.get("underlying_price"))
        strike = _number(row.get("strike"))
        iv = _number(row.get("iv"))
        dte = _number(row.get("dte"))
        if any(math.isnan(value) or value <= 0 for value in (spot, strike, iv)):
            continue
        if math.isnan(dte) or dte < 0:
            continue
        try:
            greeks = fetcher.black_scholes_greeks(
                spot=spot,
                strike=strike,
                years=max(dte, 0.25) / 365.0,
                rate=float(getattr(fetcher.settings, "risk_free_rate", 0.043)),
                volatility=iv,
                side=str(row.get("option_type") or "call").lower(),
            )
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            continue
        for name, value in greeks.items():
            if name not in out or pd.isna(out.at[idx, name]):
                out.at[idx, name] = value
        out.at[idx, "greeks_method"] = "black_scholes_modeled"

    out = _apply_expiry_identity(out)
    out["quote_provenance"] = [
        _quote_provenance(source) for source in out.get("source", pd.Series(index=out.index))
    ]
    out["greeks_provenance"] = [
        "MODELED" if str(method) == "black_scholes_modeled" else provenance
        for method, provenance in zip(
            out["greeks_method"],
            out["quote_provenance"],
            strict=False,
        )
    ]
    return out


def _normalized_option_fetch(
    self: hybrid_fetcher.DataFetcher,
    symbol: str,
    *,
    min_dte: int | None = None,
    max_dte: int | None = None,
    providers: list[str] | None = None,
    apply_guards: bool = True,
) -> FetchResult[pd.DataFrame]:
    result = _ORIGINAL_OPTION_FETCH(
        self,
        symbol,
        min_dte=min_dte,
        max_dte=max_dte,
        providers=providers,
        apply_guards=apply_guards,
    )
    result.data = normalize_expiry_chain(result.data, self)
    methods = result.data.get("classification_method", pd.Series(dtype=str)).astype(str)
    result.metadata = {
        **result.metadata,
        "expiry_fields_normalized": True,
        "expiry_identity_engine": "v1",
        "provider_classified_expiries": int(methods.str.startswith("provider_metadata:").sum()),
        "calendar_fallback_expiries": int(methods.str.contains("fallback").sum()),
        "unknown_expiry_family_count": int(
            result.data.get("expiry_family", pd.Series(dtype=str)).astype(str).eq("UNKNOWN").sum()
        ),
        "modeled_greeks_count": int(
            result.data.get("greeks_method", pd.Series(dtype=str))
            .astype(str)
            .eq("black_scholes_modeled")
            .sum()
        ),
    }
    return result


def install_expiry_chain_normalizer() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    hybrid_fetcher.DataFetcher.fetch_option_chain = _normalized_option_fetch
    _INSTALLED = True
