"""Permission-gated Massive EOD client; NEVER feed public prices or live option orders.

Massive Individual Basic market-data terms may prohibit non-display use and
derived analytics. Credentials alone cannot authorize such uses. This adapter
stays disabled until the operator has documented appropriate permissions.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

STOCK_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
OPTION_SYMBOL = re.compile(r"^O:[A-Z]{1,6}\d{6}[CP]\d{8}$")
BASE = "https://api.massive.com"
MAX_CALLS_PER_RUN = 4


def permission_state(*, key: str = "", permitted: bool = False) -> dict[str, Any]:
    if not permitted:
        return {"enabled": False, "reason": "NONDISPLAY_LICENSE_NOT_CONFIRMED",
                "source_family": "polygon_massive", "execution_eligible": False}
    if not key.strip():
        return {"enabled": False, "reason": "API_KEY_NOT_CONFIGURED",
                "source_family": "polygon_massive", "execution_eligible": False}
    return {"enabled": True, "reason": "EXPLICIT_LICENSE_CONFIRMED",
            "source_family": "polygon_massive", "execution_eligible": False}


def from_environment() -> dict[str, Any]:
    """Do not interpret possession of a free key as data-use permission."""
    return permission_state(
        key=os.getenv("MASSIVE_API_KEY", ""),
        permitted=os.getenv("MASSIVE_NONDISPLAY_LICENSE_CONFIRMED") == "true",
    )


def validate_daily_aggregates(payload: Any, ticker: str, *, end_date: date) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        return []
    if payload.get("ticker") != ticker or not isinstance(payload.get("results"), list):
        return []
    results = []
    seen = set()
    for row in payload["results"][:80]:
        if not isinstance(row, dict):
            continue
        stamp = row.get("t")
        if type(stamp) is not int or stamp < 946684800000:
            continue
        session = datetime.fromtimestamp(stamp / 1000, timezone.utc).date()
        prices = [row.get(k) for k in ("o", "h", "l", "c")]
        vol = row.get("v")
        if (session > end_date or session in seen
                or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0
                       for n in prices)
                or type(vol) not in (int, float) or not math.isfinite(vol) or vol < 0
                or prices[1] < max(prices[0], prices[3], prices[2])
                or prices[2] > min(prices[0], prices[3])):
            continue
        seen.add(session)
        results.append({"date": session.isoformat(), "open": float(prices[0]),
                        "high": float(prices[1]), "low": float(prices[2]),
                        "close": float(prices[3]), "volume": float(vol)})
    return sorted(results, key=lambda x: x["date"])


def fetch_eod(
    ticker: str, *,
    key: str, permitted: bool,
    end_date: date, lookback_days: int = 10,
    session: Any = requests,
) -> dict[str, Any]:
    state = permission_state(key=key, permitted=permitted)
    if not state["enabled"]:
        return {**state, "bars": []}
    allowed = STOCK_SYMBOL.fullmatch(ticker) or OPTION_SYMBOL.fullmatch(ticker)
    if not allowed or not 1 <= lookback_days <= 30:
        return {**state, "enabled": False, "reason": "INVALID_REQUEST", "bars": []}
    from_date = end_date - timedelta(days=lookback_days)
    url = (f"{BASE}/v2/aggs/ticker/{quote(ticker, safe=':')}/range/1/day/"
           f"{from_date.isoformat()}/{end_date.isoformat()}")
    try:
        response = session.get(
            url,
            params={"apiKey": key, "adjusted": "false", "sort": "asc", "limit": "80"},
            timeout=12,
        )
        if getattr(response, "status_code", 0) != 200:
            return {**state, "reason": "PROVIDER_HTTP_FAILURE",
                    "bars": [], "http_status": response.status_code}
        if len(getattr(response, "content", b"")) > 150_000:
            return {**state, "reason": "TOO_LARGE", "bars": []}
        bars = validate_daily_aggregates(response.json(), ticker, end_date=end_date)
        return {**state, "reason": "RESEARCH_BARS" if bars else "INVALID_OR_EMPTY",
                "bars": bars, "internal_only": True, "research_only": True}
    except (requests.RequestException, ValueError, TypeError, OverflowError):
        # Never stringify a request URL or HTTPError: URLs may contain API keys.
        return {**state, "reason": "REQUEST_FAILED", "bars": []}
