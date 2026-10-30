"""User-approved US indices and liquid US-listed mega/large-cap options focus.

Discovery priority only. This file never changes data entitlements, V11,
direction signals, contract scoring, liquidity thresholds or execution rules.
SPX / NDX are index underlyings, while SPY / QQQ are exchange-traded funds.
GOOG and GOOGL are distinct listed share classes; BABA is a US-listed ADR.
"""
from __future__ import annotations

FOCUS_INDICES = ("SPX", "NDX", "SPY", "QQQ")
FOCUS_STOCKS = (
    "TSLA", "AMD", "MU", "NVDA", "MSFT",
    "BABA", "GOOG", "GOOGL", "META",
)
# Additional established liquid large-company discovery universe.
SECONDARY_STOCKS = (
    "AAPL", "AMZN", "AVGO", "NFLX", "PLTR",
    "JPM", "COST", "ORCL", "QCOM", "XOM",
)
# The index engine handles SPX/NDX separately. These ETF+equity underlyings
# are prioritized in the generic options-contract scanner. Index option
# roots (including SPXW/NDXP) need separate verified provider entitlement.
FOCUS_OPTIONABLE = ("SPY", "QQQ", *FOCUS_STOCKS, *SECONDARY_STOCKS)
INDEX_OPTION_ROOTS = {
    "SPX": ("SPX", "SPXW"),
    "NDX": ("NDX", "NDXP"),
}
