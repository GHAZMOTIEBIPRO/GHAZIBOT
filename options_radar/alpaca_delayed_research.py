"""Opt-in Alpaca Basic research adapter: independent IEX and delayed option bars.

This does not claim full SIP/OPRA execution. The default is **no requests**.
An authorized personal/internal data-use context and owned credentials are
required. Nothing from this module may be published on a public website unless
the owner separately confirms the necessary redistribution permissions.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

import requests

STOCK = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
BASE = "https://data.alpaca.markets"
MAX_RESPONSE_BYTES = 140_000


def policy_state(*, api_key: str, secret: str, internal_use_allowed: bool) -> dict[str, Any]:
    if not internal_use_allowed:
        reason = "DATA_USE_PERMISSION_REQUIRED"
    elif not api_key or not secret:
        reason = "ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
    else:
        reason = "OPTIONAL_ACCOUNT_RESEARCH"
    return {
        "enabled": reason == "OPTIONAL_ACCOUNT_RESEARCH",
        "reason": reason,
        "source_stock": "alpaca_iex",
        "source_option": "alpaca_delayed_historical_opra_bars",
        "independent_from_yahoo": True,
        "research_only": True,
        "execution_eligible": False,
        "public_redistribution_allowed": False,
        "live_opra_quotes": False,
    }


def _valid_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _validated_bars(payload: Any, symbol: str, *, start: date, end: date,
                    kind: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), (list, dict)):
        return []
    rows = payload["bars"]
    if isinstance(rows, dict):
        if set(rows) != {symbol}:
            return []
        rows = rows.get(symbol)
    if not isinstance(rows, list) or len(rows) > 100:
        return []
    normalized: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            return []
        try:
            stamp = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            return []
        if stamp.tzinfo is None:
            return []
        day = stamp.astimezone(timezone.utc).date()
        if not start <= day <= end or day.isoformat() in normalized:
            return []
        o, h, l, c, vol = (row.get(k) for k in ("o", "h", "l", "c", "v"))
        nums=(o,h,l,c,vol)
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in nums):
            return []
        if (min(o,h,l,c) <= 0 or h < max(o,c,l) or l > min(o,c,h) or vol < 0):
            return []
        normalized[day.isoformat()] = {
            "date": day.isoformat(), "open": float(o), "high": float(h),
            "low": float(l), "close": float(c), "volume": float(vol),
            "source_feed": "IEX" if kind == "stock" else "DELAYED_HISTORICAL_OPTION_BARS",
        }
    return [normalized[key] for key in sorted(normalized)]


def _load(session: Any, endpoint: str, params: dict[str, Any],
          api_key: str, secret: str) -> dict[str, Any] | None:
    try:
        response = session.get(
            BASE + endpoint,
            params=params,
            headers={"APCA-API-KEY-ID": api_key,
                     "APCA-API-SECRET-KEY": secret},
            timeout=12,
        )
        if response.status_code != 200:
            return None
        if len(response.content) > MAX_RESPONSE_BYTES:
            return None
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("next_page_token"):
            # Incomplete pages cannot be taken as complete source history.
            return None
        return payload
    except (requests.RequestException, ValueError, TypeError):
        # Never propagate/log a URL or exception that may include credentials.
        return None


def fetch_completed_daily(
    symbol: str, *, start: date, end: date,
    kind: str = "stock", api_key: str = "", secret: str = "",
    internal_use_allowed: bool = False, now: datetime | None = None,
    session: Any = requests,
) -> dict[str, Any]:
    """Strict short date range: never request the most recent 15 minutes."""
    state = policy_state(api_key=api_key, secret=secret,
                         internal_use_allowed=internal_use_allowed)
    if not state["enabled"]:
        return {**state, "bars": []}
    now = now or datetime.now(timezone.utc)
    sym_ok = ((kind == "stock" and STOCK.fullmatch(symbol or "")) or
              (kind == "option" and OCC.fullmatch(symbol or "")))
    if (not sym_ok or not isinstance(start, date) or not isinstance(end, date)
            or now.tzinfo is None or start > end
            or not 0 <= (end - start).days <= 30
            or end >= now.astimezone(timezone.utc).date()):
        return {**state, "reason": "INVALID_OR_UNFINISHED_DAILY_WINDOW",
                "bars": []}
    params = {
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 100,
        "sort": "asc",
    }
    if kind == "stock":
        endpoint = f"/v2/stocks/{symbol}/bars"
        params.update({"feed": "iex", "adjustment": "raw"})
    else:
        # Historical bars are past OPRA-derived aggregates, not free live NBBO.
        endpoint = "/v1beta1/options/bars"
        params["symbols"] = symbol
    payload = _load(session, endpoint, params, api_key, secret)
    rows = (_validated_bars(payload, symbol, start=start, end=end, kind=kind)
            if payload is not None else [])
    return {
        **state,
        "status": "HISTORICAL_RESEARCH_BARS" if rows else "NO_VALID_BARS_OR_NOT_ENTITLED",
        "bars": rows, "exchange_scope": "IEX_ONLY" if kind == "stock" else
        "HISTORICAL_AGGREGATES_NOT_QUOTES",
        "latest_15_minutes_excluded": True,
        "account_permission_tested_live": bool(rows),
    }


def historical_option_response(
    contract: str, *, entry_date: date, end_date: date,
    api_key: str = "", secret: str = "", internal_use_allowed: bool = False,
    now: datetime | None = None, session: Any = requests,
) -> dict[str, Any]:
    if __package__:
        from .options_daily_outcome_shadow import describe_option_path
    else:
        from options_daily_outcome_shadow import describe_option_path

    result = fetch_completed_daily(
        contract, start=entry_date, end=end_date, kind="option",
        api_key=api_key, secret=secret,
        internal_use_allowed=internal_use_allowed,
        now=now, session=session,
    )
    shadow = describe_option_path(
        "O:" + contract, result["bars"],
        entry_date=entry_date.isoformat(), end_date=end_date.isoformat(),
    )
    return {
        **shadow, "entitlement": result["reason"],
        "source_family": "alpaca_historical_options",
        "internal_only": True, "execution_eligible": False,
        "public_redistribution_allowed": False,
    }
