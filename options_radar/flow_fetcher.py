from __future__ import annotations

import math
from typing import Any

import pandas as pd

from . import hybrid_fetcher

_ORIGINAL_BUILD_OPTION_ROW = hybrid_fetcher.DataFetcher._build_option_row
_INSTALLED = False


def _normalise_provider_timestamp(value: Any) -> Any:
    """Normalize provider epochs before pandas can misread milliseconds as ns."""
    if value is None or value == "":
        return value
    numeric: float | None = None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            numeric = float(stripped)
    if numeric is None or not math.isfinite(numeric):
        return value
    unit = "ms" if abs(numeric) >= 100_000_000_000 else "s"
    return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")


def _build_option_row_with_normalized_timestamp(**values: Any) -> dict[str, Any]:
    prepared = dict(values)
    prepared["updated_at"] = _normalise_provider_timestamp(
        prepared.get("updated_at")
    )
    return _ORIGINAL_BUILD_OPTION_ROW(**prepared)


def install_trade_timestamp_normalizer() -> None:
    """Install once for every DataFetcher option-chain provider."""
    global _INSTALLED
    if _INSTALLED:
        return
    hybrid_fetcher.DataFetcher._build_option_row = staticmethod(
        _build_option_row_with_normalized_timestamp
    )
    _INSTALLED = True
