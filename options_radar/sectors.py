from __future__ import annotations

from functools import lru_cache

import pandas as pd

from .providers import get_price_history


SECTOR_ETFS: dict[str, str] = {
    "NVDA": "SMH", "AMD": "SMH", "AVGO": "SMH", "MU": "SMH", "INTC": "SMH",
    "QCOM": "SMH", "ARM": "SMH", "TSM": "SMH", "ASML": "SMH", "MRVL": "SMH",
    "AAPL": "XLK", "MSFT": "XLK", "ORCL": "XLK", "CRM": "XLK", "ADBE": "XLK",
    "PLTR": "XLK", "SNOW": "IGV", "MDB": "IGV", "NET": "IGV", "CRWD": "IGV",
    "META": "XLC", "GOOGL": "XLC", "GOOG": "XLC", "NFLX": "XLC", "ROKU": "XLC",
    "DIS": "XLC", "SNAP": "XLC", "PINS": "XLC", "RDDT": "XLC",
    "AMZN": "XLY", "TSLA": "XLY", "NKE": "XLY", "SBUX": "XLY", "MCD": "XLY",
    "HD": "XLY", "LOW": "XLY", "DKNG": "XLY", "RIVN": "XLY", "LCID": "XLY",
    "JPM": "XLF", "BAC": "XLF", "C": "XLF", "WFC": "XLF", "GS": "XLF",
    "MS": "XLF", "COIN": "FINX", "HOOD": "FINX", "SOFI": "FINX",
    "AMGN": "XBI", "GILD": "XBI", "MRNA": "XBI", "BNTX": "XBI", "BIIB": "XBI",
    "REGN": "XBI", "VRTX": "XBI", "IOVA": "XBI", "CRSP": "XBI", "EDIT": "XBI",
    "LLY": "XLV", "UNH": "XLV", "JNJ": "XLV", "PFE": "XLV", "ABBV": "XLV",
    "XOM": "XLE", "CVX": "XLE", "OXY": "XLE", "SLB": "XLE", "COP": "XLE",
    "BA": "XLI", "CAT": "XLI", "GE": "XLI", "DE": "XLI", "LMT": "XLI",
    "FCX": "XLB", "NUE": "XLB", "CLF": "XLB",
    "WMT": "XLP", "COST": "XLP", "KO": "XLP", "PEP": "XLP",
    "NEE": "XLU", "DUK": "XLU", "PLD": "XLRE", "O": "XLRE",
}


@lru_cache(maxsize=64)
def _history(symbol: str) -> pd.DataFrame:
    try:
        return get_price_history(symbol, period="6mo")
    except Exception:
        return pd.DataFrame()


def _return(frame: pd.DataFrame, sessions: int) -> float:
    if frame is None or frame.empty or "Close" not in frame or len(frame) <= sessions:
        return 0.0
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) <= sessions or float(close.iloc[-sessions - 1]) == 0:
        return 0.0
    return float(close.iloc[-1] / close.iloc[-sessions - 1] - 1.0)


def _neutral(etf: str = "SPY") -> dict[str, float | str]:
    return {
        "sector_etf": etf,
        "stock_return_5d": 0.0,
        "stock_return_20d": 0.0,
        "sector_return_5d": 0.0,
        "sector_return_20d": 0.0,
        "relative_strength_5d": 0.0,
        "relative_strength_20d": 0.0,
        "sector_vs_market": 0.0,
        "sector_score": 0.0,
    }


def sector_context(symbol: str, stock_history: pd.DataFrame | None = None) -> dict[str, float | str]:
    symbol = str(symbol).upper()
    etf = SECTOR_ETFS.get(symbol)
    if not etf:
        return _neutral()
    try:
        stock = stock_history if stock_history is not None and not stock_history.empty else _history(symbol)
        sector = _history(etf)
        spy = _history("SPY")
        stock_5 = _return(stock, 5)
        stock_20 = _return(stock, 20)
        sector_5 = _return(sector, 5)
        sector_20 = _return(sector, 20)
        spy_5 = _return(spy, 5)
        spy_20 = _return(spy, 20)
        rs_5 = stock_5 - sector_5
        rs_20 = stock_20 - sector_20
        sector_vs_market = 0.4 * (sector_5 - spy_5) + 0.6 * (sector_20 - spy_20)
        combined = 0.4 * rs_5 + 0.6 * rs_20 + 0.35 * sector_vs_market
        score = max(-8.0, min(8.0, combined * 120.0))
    except Exception:
        return _neutral(etf)
    return {
        "sector_etf": etf,
        "stock_return_5d": stock_5,
        "stock_return_20d": stock_20,
        "sector_return_5d": sector_5,
        "sector_return_20d": sector_20,
        "relative_strength_5d": rs_5,
        "relative_strength_20d": rs_20,
        "sector_vs_market": sector_vs_market,
        "sector_score": score,
    }
