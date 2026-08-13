from __future__ import annotations

from typing import Any

import pandas as pd

_INDEX_TECHNICAL_ALIASES: dict[str, tuple[str, float]] = {
    "SPX": ("^GSPC", 1.0),
    "VIX": ("^VIX", 1.0),
    "RUT": ("^RUT", 1.0),
    "NDX": ("^NDX", 1.0),
    "XSP": ("^GSPC", 0.1),
}


def normalize_expiration_frame(chain: pd.DataFrame) -> pd.DataFrame:
    """Normalize option expirations to timezone-naive trading dates.

    Option expiration is a calendar date, not a moment-in-time. Providers may
    nevertheless emit timezone-aware timestamps. Converting to UTC and then
    dropping timezone metadata prevents tz-aware/naive subtraction failures
    without changing the expiration date used by the DTE filter.
    """
    out = chain.copy()
    if "expiration" not in out:
        return out
    expiration = pd.to_datetime(out["expiration"], errors="coerce", utc=True)
    out["expiration"] = expiration.dt.tz_localize(None)
    return out


def technical_alias(symbol: str) -> tuple[str, float]:
    normalized = str(symbol or "").upper().strip()
    return _INDEX_TECHNICAL_ALIASES.get(normalized, (normalized, 1.0))


def rescale_ohlc(frame: pd.DataFrame, scale: float) -> pd.DataFrame:
    if frame is None or frame.empty or scale == 1.0:
        return frame.copy() if frame is not None else pd.DataFrame()
    out = frame.copy()
    for column in ("Open", "High", "Low", "Close"):
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce") * float(scale)
    return out


def install_options_radar_hardening() -> None:
    """Install runtime guards without changing contract identity.

    This is intentionally explicit and idempotent. It hardens the independent
    options runner while leaving the stock path untouched.
    """
    from options_radar.indicators import analyze_technical
    from options_radar.providers import get_price_history
    from options_radar.scanner import OptionsRadar

    if getattr(OptionsRadar, "_ghazi_runtime_hardened", False):
        return

    original_technical = OptionsRadar._technical

    @staticmethod
    def prepare_chain_dates(chain: pd.DataFrame) -> pd.DataFrame:
        out = normalize_expiration_frame(chain)
        if "expiration" in out:
            expiration = pd.to_datetime(out["expiration"], errors="coerce")
            if (
                "dte" not in out
                or pd.to_numeric(out["dte"], errors="coerce").isna().all()
            ):
                today = pd.Timestamp.now().normalize()
                out["dte"] = (expiration.dt.normalize() - today).dt.days
        return out

    def technical(self: Any, symbol: str):
        alias, scale = technical_alias(symbol)
        if alias == str(symbol or "").upper().strip() and scale == 1.0:
            return original_technical(self, symbol)
        try:
            history = self.fetcher.fetch_stock_bars(alias, interval="1d").data
        except Exception:
            history = get_price_history(alias, period="1y")
        history = rescale_ohlc(history, scale)
        return analyze_technical(str(symbol or "").upper().strip(), history)

    OptionsRadar._prepare_chain_dates = prepare_chain_dates
    OptionsRadar._technical = technical
    OptionsRadar._ghazi_runtime_hardened = True
