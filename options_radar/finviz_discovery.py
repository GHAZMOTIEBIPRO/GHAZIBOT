"""Optional Finviz discovery adapter; never an execution-grade price source.

Finviz can block automation or return delayed snapshots. Fail closed, preserve
provenance, and leave SEC/market validation to existing Omega engines.
"""
from __future__ import annotations

import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")


def discover_finviz_symbols(*, filters: dict[str, Any] | None = None,
                            limit: int = 100) -> list[dict[str, str]]:
    """Return research-only ticker candidates; [] if optional dependency fails."""
    try:
        from finvizfinance.screener.overview import Overview
    except ImportError:
        LOGGER.info("Finviz adapter inactive: finvizfinance not installed")
        return []
    try:
        scanner = Overview()
        scanner.set_filter(filters_dict=filters or {
            "Average Volume": "Over 500K",
            "Relative Volume": "Over 2",
        })
        frame = scanner.screener_view()
    except Exception as exc:
        LOGGER.warning("Finviz discovery unavailable: %s", exc)
        return []
    if frame is None or "Ticker" not in frame.columns:
        return []
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for raw in frame["Ticker"]:
        symbol = str(raw).strip().upper()
        if not _SYMBOL.fullmatch(symbol) or symbol in seen:
            continue
        seen.add(symbol)
        results.append({
            "symbol": symbol,
            "source": "Finviz screener",
            "authority": "research_only",
            "price_freshness": "unverified",
        })
        if len(results) >= max(1, min(limit, 500)):
            break
    return results
