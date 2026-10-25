"""Replaceable bar providers for the multi-timeframe engine and the private scan.

A provider returns raw, validated bars and its rights source name; it never
decides what may be published (that is options_radar.output_policy). The
engine can swap providers without touching the computation or the sinks.

AlpacaBars (Alpaca Market Data v2, Basic plan as documented on
docs.alpaca.markets, read on the runner in run 40238841187):
- Historical bars: "the `end` parameter must be at least 15 minutes old to
  query SIP data without a subscription". SIP is the consolidated tape (all
  U.S. exchanges), so completed bars older than 15 minutes default to
  feed=sip; every request ends at least 16 minutes in the past. If the
  account refuses SIP, the same request is repeated once with feed=iex and
  the result is labelled IEX (one venue, partial volume) - history and
  current bars of a symbol always come from one feed.
- Snapshots (latest trade, today's bar) need a subscription for SIP, so they
  use feed=iex and are labelled IEX.
- "the bar is only emitted if none of its fields are 0": a missing 5-minute
  bar means no qualifying trade, not a data fault.
- Basic plan: 200 historical calls per minute; requests are batched.
The provider is called only when output_policy allows `fetch`.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Protocol

import requests

from options_radar.output_policy import decide

BASE = "https://data.alpaca.markets"
TRADING_BASES = ("https://paper-api.alpaca.markets", "https://api.alpaca.markets")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
MAX_PAGES = 12
DELAY = timedelta(minutes=16)
COVERAGE = {"sip": "SIP: all U.S. exchanges (consolidated tape)", "iex": "IEX: one exchange, partial volume"}


class BarProvider(Protocol):
    name: str
    rights_source: str

    def bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> dict[str, Any]: ...


def _parse(rows: Any) -> list[dict[str, Any]] | None:
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
    name = "alpaca"
    rights_source = "alpaca_iex"  # Alpaca market data under the account holder's data agreement
    TIMEFRAMES: ClassVar[dict[str, str]] = {"5m": "5Min", "1d": "1Day"}

    def __init__(self, env: Mapping[str, str], session: Any = requests, now: datetime | None = None):
        self.env, self.session = env, session
        self.now = now or datetime.now(timezone.utc)
        self.calls = 0

    def status(self) -> str:
        decision = decide(self.rights_source, "fetch", self.env)
        if not decision.allowed:
            return "DENIED_BY_POLICY"
        if not (self.env.get("ALPACA_API_KEY") or "").strip() or not (self.env.get("ALPACA_SECRET_KEY") or "").strip():
            return "CREDENTIALS_MISSING"
        return "READY"

    def preferred_feed(self) -> str:
        return "iex" if (self.env.get("ALPACA_BARS_FEED") or "").strip().lower() == "iex" else "sip"

    def _headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self.env["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": self.env["ALPACA_SECRET_KEY"]}

    def _get(self, url: str, params: dict[str, Any]) -> tuple[str, Any]:
        self.calls += 1
        try:
            response = self.session.get(url, params=params, headers=self._headers(), timeout=20)
            if response.status_code != 200:
                return f"HTTP_{response.status_code}", None
            return "OK", response.json()
        except (requests.RequestException, ValueError):
            return "UNAVAILABLE", None  # never log the URL or exception text (may carry credentials)

    def _paged(self, url: str, params: dict[str, Any], multi: bool) -> tuple[str, Any]:
        merged: Any = {} if multi else []
        for _ in range(MAX_PAGES):
            status, payload = self._get(url, params)
            if status != "OK":
                return status, None
            raw = payload.get("bars") if isinstance(payload, dict) else None
            if multi:
                if raw is None:
                    raw = {}
                if not isinstance(raw, dict):
                    return "MALFORMED", None
                for sym, rows in raw.items():
                    parsed = _parse(rows)
                    if parsed is None:
                        return "MALFORMED", None
                    merged.setdefault(sym, []).extend(parsed)
            else:
                parsed = _parse(raw if raw is not None else [])
                if parsed is None:
                    return "MALFORMED", None
                merged.extend(parsed)
            token = payload.get("next_page_token")
            if not token:
                return "OK", merged
            params = {**params, "page_token": token}
        return "TRUNCATED", None  # incomplete history is not used

    def _request(self, path: str, params: dict[str, Any], multi: bool) -> tuple[str, str, Any]:
        """Try the preferred feed; on refusal of SIP, repeat once with IEX and say so."""
        feed = self.preferred_feed()
        status, data = self._paged(f"{BASE}{path}", {**params, "feed": feed}, multi)
        if status in ("HTTP_403", "HTTP_422") and feed == "sip":
            feed = "iex"
            status, data = self._paged(f"{BASE}{path}", {**params, "feed": feed}, multi)
        return status, feed, data

    def _window(self, timeframe: str, start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
        if timeframe not in self.TIMEFRAMES or start.tzinfo is None:
            return None
        end = min(end, self.now - DELAY)
        return (start, end) if start < end else None

    def bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> dict[str, Any]:
        base = {"provider": self.name, "timeframe": timeframe, "bars": []}
        status = self.status()
        if status != "READY":
            return {**base, "status": status}
        window = self._window(timeframe, start, end)
        if not SYMBOL.fullmatch(symbol or "") or window is None:
            return {**base, "status": "INVALID_REQUEST"}
        params = {"timeframe": self.TIMEFRAMES[timeframe], "start": window[0].isoformat(), "end": window[1].isoformat(),
                  "adjustment": "split", "limit": 10000, "sort": "asc"}
        status, feed, rows = self._request(f"/v2/stocks/{symbol}/bars", params, multi=False)
        if status != "OK":
            return {**base, "status": status, "feed": feed}
        return {**base, "status": "OK", "feed": feed, "coverage": COVERAGE[feed], "bars": rows,
                "requested_end": window[1].isoformat()}

    def multi_bars(self, symbols: list[str], timeframe: str, start: datetime, end: datetime,
                   batch: int = 100) -> dict[str, Any]:
        """Bars for many symbols in batches; per-batch failures are reported, not fatal."""
        out: dict[str, Any] = {"status": self.status(), "bars": {}, "feed": {}, "failed_batches": 0, "batches": 0}
        if out["status"] != "READY":
            return out
        window = self._window(timeframe, start, end)
        valid = [s for s in symbols if SYMBOL.fullmatch(s or "")]
        if window is None:
            return {**out, "status": "INVALID_REQUEST"}
        for i in range(0, len(valid), batch):
            chunk = valid[i:i + batch]
            out["batches"] += 1
            params = {"symbols": ",".join(chunk), "timeframe": self.TIMEFRAMES[timeframe],
                      "start": window[0].isoformat(), "end": window[1].isoformat(), "adjustment": "split",
                      "limit": 10000, "sort": "asc"}
            status, feed, data = self._request("/v2/stocks/bars", params, multi=True)
            if status != "OK":
                out["failed_batches"] += 1
                continue
            for sym, rows in data.items():
                out["bars"][sym] = rows
                out["feed"][sym] = feed
        out["status"] = "OK" if out["batches"] > out["failed_batches"] else "ALL_BATCHES_FAILED"
        return out

    def snapshots(self, symbols: list[str], batch: int = 500) -> dict[str, Any]:
        """Latest IEX snapshot per symbol (real-time SIP needs a subscription)."""
        out: dict[str, Any] = {"status": self.status(), "snapshots": {}, "feed": "iex", "coverage": COVERAGE["iex"],
                               "failed_batches": 0}
        if out["status"] != "READY":
            return out
        valid = [s for s in symbols if SYMBOL.fullmatch(s or "")]
        for i in range(0, len(valid), batch):
            status, data = self._get(f"{BASE}/v2/stocks/snapshots", {"symbols": ",".join(valid[i:i + batch]), "feed": "iex"})
            if status != "OK" or not isinstance(data, dict):
                out["failed_batches"] += 1
                continue
            for sym, snap in data.items():
                if not isinstance(snap, dict):
                    continue
                day, prev, trade = snap.get("dailyBar"), snap.get("prevDailyBar"), snap.get("latestTrade")
                if not (isinstance(day, dict) and isinstance(prev, dict) and isinstance(trade, dict)):
                    continue
                try:
                    out["snapshots"][sym] = {"price": float(trade["p"]), "trade_time": str(trade["t"]),
                                             "prev_close": float(prev["c"]), "day_volume_iex": float(day["v"])}
                except (KeyError, TypeError, ValueError):
                    continue
        out["status"] = "OK" if out["snapshots"] else "NO_SNAPSHOTS"
        return out

    def assets(self) -> dict[str, Any]:
        """Active, tradable U.S. equities from the account's Trading API (the scan universe)."""
        out: dict[str, Any] = {"status": self.status(), "symbols": [], "excluded": {}}
        if out["status"] != "READY":
            return out
        for base in TRADING_BASES:  # paper keys answer on the paper host, live keys on the live host
            status, data = self._get(f"{base}/v2/assets", {"status": "active", "asset_class": "us_equity"})
            if status == "OK" and isinstance(data, list):
                break
        else:
            return {**out, "status": "ASSETS_" + status}
        excluded: dict[str, int] = {}
        for asset in data:
            if not isinstance(asset, dict):
                continue
            reason = ("NOT_TRADABLE" if not asset.get("tradable") else
                      "OTC_OR_OTHER_VENUE" if asset.get("exchange") not in ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
                      else "SYMBOL_FORMAT" if not SYMBOL.fullmatch(str(asset.get("symbol") or "")) else None)
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
            else:
                out["symbols"].append(asset["symbol"])
        return {**out, "status": "OK", "excluded": excluded}
