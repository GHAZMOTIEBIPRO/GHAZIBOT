from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from . import hybrid_fetcher
from .hybrid_fetcher import FetchResult

_ORIGINAL_OPTION_FETCH = hybrid_fetcher.DataFetcher.fetch_option_chain
_INSTALLED = False


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


def normalize_expiry_chain(
    frame: pd.DataFrame,
    fetcher: hybrid_fetcher.DataFetcher,
) -> pd.DataFrame:
    """Restore expiry fields lost by provider merges and model missing Greeks.

    Provider composites use a compact common schema which can omit DTE. Yahoo
    also does not publish contract Greeks. The expiry radar needs both values,
    so DTE is recomputed from the expiration timestamp and missing Greeks are
    estimated with the existing Black-Scholes screening model. Modeled values
    remain explicitly labelled and never turn an unofficial quote into a
    licensed/primary source.
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
    result.metadata = {
        **result.metadata,
        "expiry_fields_normalized": True,
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
