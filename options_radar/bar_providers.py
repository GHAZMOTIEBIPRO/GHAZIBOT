"""Replaceable bar providers for the multi-timeframe engine.

A provider returns raw, validated bars and its rights source name; it never
decides what may be published (that is options_radar.output_policy). The
engine can swap providers without touching the computation or the sinks.

AlpacaBars: Alpaca Market Data v2 stock bars, IEX feed (the free plan's
real-time feed is IEX only; IEX is one venue, so volume is partial). The
request end is held at least 16 minutes in the past so that no bar inside
the latest 15 minutes is ever requested, and the provider is called only
when output_policy allows `fetch` (owner authorization + keys).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Protocol

import requests

from options_radar.output_policy import decide

BASE = "https://data.alpaca.markets"
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
MAX_PAGES = 6
DELAY = timedelta(minutes=16)


class BarProvider(Protocol):
    name: str
    rights_source: str

    def bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> dict[str, Any]: ...


def _parse(rows: Any, symbol: str) -> list[dict[str, Any]] | None:
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        try:
            stamp = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            return None
        if stamp.tzinfo is None:
            return None
        vals = [row.get(k) for k in ("o", "h", "l", "c", "v")]
        if any(type(v) not in (int, float) for v in vals):
            return None
        out.append({"t": stamp.astimezone(timezone.utc), "o": float(vals[0]), "h": float(vals[1]),
                    "l": float(vals[2]), "c": float(vals[3]), "v": float(vals[4])})
    return out


class AlpacaBars:
    name = "alpaca_iex"
    rights_source = "alpaca_iex"
    TIMEFRAMES: ClassVar[dict[str, str]] = {"5m": "5Min", "1d": "1Day"}

    def __init__(self, env: Mapping[str, str], session: Any = requests, now: datetime | None = None):
        self.env, self.session = env, session
        self.now = now or datetime.now(timezone.utc)

    def status(self) -> str:
        decision = decide(self.rights_source, "fetch", self.env)
        if not decision.allowed:
            return "DENIED_BY_POLICY"
        if not (self.env.get("ALPACA_API_KEY") or "").strip() or not (self.env.get("ALPACA_SECRET_KEY") or "").strip():
            return "CREDENTIALS_MISSING"
        return "READY"

    def bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> dict[str, Any]:
        status = self.status()
        base = {"provider": self.name, "feed": "iex", "timeframe": timeframe, "bars": []}
        if status != "READY":
            return {**base, "status": status}
        if not SYMBOL.fullmatch(symbol or "") or timeframe not in self.TIMEFRAMES or start.tzinfo is None:
            return {**base, "status": "INVALID_REQUEST"}
        end = min(end, self.now - DELAY)
        if start >= end:
            return {**base, "status": "INVALID_REQUEST"}
        params: dict[str, Any] = {"timeframe": self.TIMEFRAMES[timeframe], "start": start.isoformat(),
                                  "end": end.isoformat(), "feed": "iex", "adjustment": "split",
                                  "limit": 10000, "sort": "asc"}
        headers = {"APCA-API-KEY-ID": self.env["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": self.env["ALPACA_SECRET_KEY"]}
        rows: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            try:
                response = self.session.get(f"{BASE}/v2/stocks/{symbol}/bars", params=params, headers=headers, timeout=15)
                if response.status_code != 200:
                    return {**base, "status": f"HTTP_{response.status_code}"}
                payload = response.json()
            except (requests.RequestException, ValueError):
                # never log the URL or the exception text (may carry credentials)
                return {**base, "status": "UNAVAILABLE"}
            page = _parse(payload.get("bars") if isinstance(payload, dict) else None, symbol)
            if page is None:
                return {**base, "status": "MALFORMED"}
            rows.extend(page)
            token = payload.get("next_page_token")
            if not token:
                return {**base, "status": "OK", "bars": rows, "requested_end": end.isoformat()}
            params["page_token"] = token
        return {**base, "status": "TRUNCATED", "bars": []}  # incomplete history is not used
