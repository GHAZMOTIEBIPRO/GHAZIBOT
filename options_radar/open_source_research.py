from __future__ import annotations

from importlib import import_module, metadata
from typing import Any

import pandas as pd


_REQUIRED_OHLC = ("open", "high", "low", "close")


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not-installed"


def normalize_ohlcv(history: pd.DataFrame) -> pd.DataFrame:
    """Return the lowercase OHLCV shape expected by smartmoneyconcepts."""
    if history is None or history.empty:
        raise ValueError("OHLC history is empty")
    lookup = {str(column).lower(): column for column in history.columns}
    missing = [name for name in _REQUIRED_OHLC if name not in lookup]
    if missing:
        raise ValueError(f"Missing OHLC columns: {missing}")

    frame = pd.DataFrame(
        {
            name: pd.to_numeric(history[lookup[name]], errors="coerce")
            for name in _REQUIRED_OHLC
        }
    )
    if "volume" in lookup:
        frame["volume"] = pd.to_numeric(history[lookup["volume"]], errors="coerce")
    else:
        frame["volume"] = 0.0
    return frame.dropna(subset=list(_REQUIRED_OHLC)).reset_index(drop=True)


def _last_confirmed_event(
    frame: pd.DataFrame,
    signal_column: str,
    *,
    max_index: int,
    value_columns: tuple[str, ...],
) -> dict[str, Any] | None:
    if frame is None or frame.empty or signal_column not in frame.columns or max_index < 0:
        return None
    limited = frame.iloc[: max_index + 1]
    mask = limited[signal_column].notna()
    if not mask.any():
        return None
    index = int(limited.index[mask][-1])
    row = limited.loc[index]
    payload: dict[str, Any] = {"index": index}
    for name in (signal_column, *value_columns):
        if name not in limited.columns:
            continue
        value = row.get(name)
        if pd.isna(value):
            payload[name] = None
        elif hasattr(value, "item"):
            payload[name] = value.item()
        else:
            payload[name] = value
    return payload


def build_hindsight_safe_smc_snapshot(
    history: pd.DataFrame,
    *,
    swing_length: int = 20,
) -> dict[str, Any]:
    """Run smartmoneyconcepts as research-only shadow evidence with confirmation lag.

    The upstream swing detector uses candles before and after a candidate swing.
    We therefore exclude the most recent swing_length bars from swing evidence.
    FVG evidence is held back by one bar because its definition needs the next
    candle. These outputs are never allowed to create execution authority.
    """
    if swing_length < 2:
        raise ValueError("swing_length must be >= 2")
    ohlcv = normalize_ohlcv(history)
    if len(ohlcv) < (2 * swing_length + 5):
        raise ValueError("Not enough OHLC rows for hindsight-safe SMC validation")

    module = import_module("smartmoneyconcepts")
    smc = getattr(module, "smc")

    fvg = smc.fvg(ohlcv, join_consecutive=False)
    swings = smc.swing_highs_lows(ohlcv, swing_length=swing_length)

    last_bar = len(ohlcv) - 1
    fvg_cutoff = last_bar - 1
    swing_cutoff = last_bar - swing_length

    confirmed_fvg = _last_confirmed_event(
        fvg,
        "FVG",
        max_index=fvg_cutoff,
        value_columns=("Top", "Bottom", "MitigatedIndex"),
    )
    confirmed_swing = _last_confirmed_event(
        swings,
        "HighLow",
        max_index=swing_cutoff,
        value_columns=("Level",),
    )

    return {
        "library": "smartmoneyconcepts",
        "library_version": _package_version("smartmoneyconcepts"),
        "research_only": True,
        "live_decision_authority": False,
        "bars": len(ohlcv),
        "swing_length": swing_length,
        "fvg_confirmation_lag_bars": 1,
        "swing_confirmation_lag_bars": swing_length,
        "safe_swing_cutoff_index": swing_cutoff,
        "last_confirmed_fvg": confirmed_fvg,
        "last_confirmed_swing": confirmed_swing,
        "warning": (
            "SMC labels are descriptive research features. They do not prove "
            "institutional orders, dealer intent, or future price direction."
        ),
    }


def edgartools_capabilities() -> dict[str, Any]:
    """Inspect the optional EdgarTools bridge without making a network request."""
    try:
        module = import_module("edgar")
    except ImportError:
        return {
            "library": "edgartools",
            "library_version": _package_version("edgartools"),
            "available": False,
            "research_only": True,
            "live_decision_authority": False,
        }

    capabilities = {
        name: bool(getattr(module, name, None))
        for name in ("Company", "Filings", "set_identity")
    }
    return {
        "library": "edgartools",
        "library_version": _package_version("edgartools"),
        "available": True,
        "capabilities": capabilities,
        "research_only": True,
        "live_decision_authority": False,
        "authority_note": (
            "Official SEC endpoints remain the filing source of truth; EdgarTools "
            "is an optional parsing/enrichment layer."
        ),
    }


def build_open_source_research_snapshot(history: pd.DataFrame) -> dict[str, Any]:
    return {
        "edgartools": edgartools_capabilities(),
        "smart_money_concepts": build_hindsight_safe_smc_snapshot(history),
    }
