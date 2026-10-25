"""Replaceable market-discovery providers for the explosion radar.

Discovery only says why a symbol is worth measuring (top mover, most active);
it carries no score. The provider is chosen by output_policy for the use the
output needs, so the engine is no longer tied to one source:

- nasdaq_web screener: the original full-market discovery; its terms forbid
  automated capture, so policy denies it (no request is made).
- Alpaca screener (movers, most actives): owner's internal use only, so it
  can feed the private scan and never the public site.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from options_radar.output_policy import decide, decide_all

BASE = "https://data.alpaca.markets/v1beta1/screener/stocks"
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
MAX_AGE = timedelta(minutes=45)


class NasdaqScreenerDiscovery:
    name = "nasdaq_screener"
    rights_source = "nasdaq_web"

    def __init__(self, env: Mapping[str, str]):
        self.env = env

    def candidates(self, now: datetime) -> dict[str, Any]:
        decision = decide(self.rights_source, "fetch", self.env)
        return {"provider": self.name, "status": "DENIED_BY_POLICY" if not decision.allowed else "NOT_WIRED",
                "reason": decision.reason, "candidates": []}


class AlpacaScreenerDiscovery:
    name = "alpaca_screener"
    rights_source = "alpaca_iex"

    def __init__(self, env: Mapping[str, str], session: Any = requests, top: int = 20):
        self.env, self.session, self.top = env, session, top

    def _get(self, path: str, params: dict[str, Any]) -> tuple[str, Any]:
        headers = {"APCA-API-KEY-ID": self.env.get("ALPACA_API_KEY", ""),
                   "APCA-API-SECRET-KEY": self.env.get("ALPACA_SECRET_KEY", "")}
        try:
            response = self.session.get(f"{BASE}/{path}", params=params, headers=headers, timeout=12)
            if response.status_code != 200:
                return f"HTTP_{response.status_code}", None
            return "OK", response.json()
        except (requests.RequestException, ValueError):
            return "UNAVAILABLE", None  # no URL or exception text in logs

    def candidates(self, now: datetime) -> dict[str, Any]:
        base = {"provider": self.name, "candidates": []}
        decision = decide(self.rights_source, "fetch", self.env)
        if not decision.allowed:
            return {**base, "status": "DENIED_BY_POLICY", "reason": decision.reason}
        if not (self.env.get("ALPACA_API_KEY") or "").strip() or not (self.env.get("ALPACA_SECRET_KEY") or "").strip():
            return {**base, "status": "CREDENTIALS_MISSING"}
        status, movers = self._get("movers", {"top": self.top})
        if status != "OK":
            return {**base, "status": status}
        status_active, actives = self._get("most-actives", {"by": "volume", "top": self.top})
        if not isinstance(movers, dict):
            return {**base, "status": "MALFORMED"}
        try:
            updated = datetime.fromisoformat(str(movers.get("last_updated")).replace("Z", "+00:00"))
        except ValueError:
            return {**base, "status": "UNTIMED"}  # provider time is required; now() is not a substitute
        if updated.tzinfo is None:
            return {**base, "status": "UNTIMED"}
        if now - updated > MAX_AGE:
            return {**base, "status": "STALE", "provider_time": updated.isoformat()}
        found: dict[str, dict[str, Any]] = {}
        for row in movers.get("gainers") or []:
            if isinstance(row, dict) and SYMBOL.fullmatch(str(row.get("symbol") or "")):
                found[row["symbol"]] = {"symbol": row["symbol"], "why": "TOP_GAINER",
                                        "percent_change": row.get("percent_change")}
        for row in (actives or {}).get("most_actives") or [] if status_active == "OK" else []:
            if isinstance(row, dict) and SYMBOL.fullmatch(str(row.get("symbol") or "")):
                found.setdefault(row["symbol"], {"symbol": row["symbol"], "why": "MOST_ACTIVE"})
        return {**base, "status": "OK", "provider_time": updated.isoformat(), "candidates": list(found.values())}


def select(providers: list[Any], use: str, env: Mapping[str, str]) -> tuple[Any | None, list[dict[str, str]]]:
    """First provider whose source allows both fetching and the output's use."""
    tried = []
    for provider in providers:
        decision = decide_all([provider.rights_source], "fetch", env)
        if decision.allowed:
            decision = decide_all([provider.rights_source], use, env)
        tried.append({"provider": provider.name, "allowed": str(decision.allowed), "reason": decision.reason})
        if decision.allowed:
            return provider, tried
    return None, tried


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
