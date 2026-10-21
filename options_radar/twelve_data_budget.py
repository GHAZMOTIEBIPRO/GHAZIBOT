"""Twelve Data credit budget, quota guard and in-memory request cache.

Prepared before any key exists so the adapters are safe the day one is
added. Nothing here makes Twelve Data publishable: its terms allow
Internal Use only (data/source_rights.json), so outputs stay internal and
public_guard keeps blocking them.

- Plan limits come from TWELVE_DATA_CREDITS_PER_MINUTE / _PER_DAY, else
  the Basic (free) plan figures recorded in FREE_PLAN with their source.
- ENGINE_PLAN states each engine's symbols, interval and runs per day;
  plan_report() proves the daily total fits under the plan with headroom,
  and the test suite fails if a change breaks that.
- CreditGuard enforces a per-run allowance and the per-minute limit inside
  one process; a provider "out of credits" answer raises QuotaExhausted so
  callers publish QUOTA_EXHAUSTED instead of empty or stale numbers.
- RequestCache dedupes identical requests within one process for at most
  one bar interval. Nothing is written to disk: the terms forbid storing
  or caching data beyond the timeframes in the documentation.
"""
from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Basic (free) plan, https://twelvedata.com/pricing.md read by run 39566940801:
# "| Basic | $0/mo | 8 (800/day cap) | 8 (trial) | US | ..." and "Free and Basic
# plans add an 800-request/day cap on top of the per-minute limit". The same
# page limits Basic to "internal non-display usage only".
FREE_PLAN = {"credits_per_minute": 8, "credits_per_day": 800}
FREE_PLAN_VERIFIED = True
DAILY_HEADROOM = 0.8          # plan at most 80% of the daily credits
MINUTE_HEADROOM = 1.0
# Credits per symbol for the endpoints the adapters use (time_series, quote).
ENDPOINT_COST = {"time_series": 1, "quote": 1}
INTERVAL_SECONDS = {"1min": 60, "5min": 300, "15min": 900, "30min": 1800, "1h": 3600, "4h": 14400, "1day": 86400}


@dataclass(frozen=True)
class EngineBudget:
    symbols: int
    interval: str
    runs_per_day: int
    endpoint: str = "time_series"

    @property
    def credits_per_run(self) -> int:
        return self.symbols * ENDPOINT_COST[self.endpoint]

    @property
    def credits_per_day(self) -> int:
        return self.credits_per_run * self.runs_per_day


# Tiered refresh: intraday context for the few index ETFs, slower cadence
# for wider lists, daily bars once after the close. Runs per day count the
# 6.5 regular-session hours only.
ENGINE_PLAN: dict[str, EngineBudget] = {
    "index_etfs_15min": EngineBudget(symbols=4, interval="15min", runs_per_day=26),       # SPY QQQ IWM DIA
    "large_caps_1h": EngineBudget(symbols=20, interval="1h", runs_per_day=7),
    "watchlist_daily": EngineBudget(symbols=60, interval="1day", runs_per_day=1),
    "independent_price_check": EngineBudget(symbols=8, interval="1day", runs_per_day=4),
    "catalyst_price_band": EngineBudget(symbols=20, interval="1day", runs_per_day=1, endpoint="quote"),
}


def plan_limits(env: dict[str, str] | None = None) -> dict[str, int]:
    env = os.environ if env is None else env
    out = dict(FREE_PLAN)
    for key, var in (("credits_per_minute", "TWELVE_DATA_CREDITS_PER_MINUTE"),
                     ("credits_per_day", "TWELVE_DATA_CREDITS_PER_DAY")):
        raw = str(env.get(var, "")).strip()
        if raw.isdigit() and int(raw) > 0:
            out[key] = int(raw)
    return out


def plan_report(limits: dict[str, int] | None = None,
                plan: dict[str, EngineBudget] | None = None) -> dict[str, Any]:
    limits = limits or plan_limits()
    plan = ENGINE_PLAN if plan is None else plan
    engines = {name: {"symbols": b.symbols, "interval": b.interval, "runs_per_day": b.runs_per_day,
                      "credits_per_run": b.credits_per_run, "credits_per_day": b.credits_per_day,
                      "minutes_per_run_at_limit": -(-b.credits_per_run // limits["credits_per_minute"])}
               for name, b in plan.items()}
    total = sum(e["credits_per_day"] for e in engines.values())
    allowed = int(limits["credits_per_day"] * DAILY_HEADROOM)
    return {"limits": limits, "engines": engines, "planned_credits_per_day": total,
            "allowed_credits_per_day": allowed, "fits": total <= allowed,
            "headroom_credits": allowed - total}


class QuotaExhausted(RuntimeError):
    """Provider credits or the planned allowance are used up; publish QUOTA_EXHAUSTED."""


@dataclass
class CreditGuard:
    per_minute: int
    per_run: int
    max_wait_seconds: float = 65.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    used: int = 0
    _window: deque = field(default_factory=deque)

    @classmethod
    def for_engine(cls, engine: str, limits: dict[str, int] | None = None, **kwargs: Any) -> CreditGuard:
        limits = limits or plan_limits()
        return cls(per_minute=int(limits["credits_per_minute"] * MINUTE_HEADROOM),
                   per_run=ENGINE_PLAN[engine].credits_per_run, **kwargs)

    def _spent_last_minute(self, now: float) -> int:
        while self._window and now - self._window[0][0] >= 60:
            self._window.popleft()
        return sum(cost for _, cost in self._window)

    def acquire(self, cost: int) -> None:
        if cost <= 0:
            return
        if cost > self.per_minute:
            raise QuotaExhausted(f"one request needs {cost} credits, above {self.per_minute} per minute")
        if self.used + cost > self.per_run:
            raise QuotaExhausted(f"run allowance of {self.per_run} credits used")
        waited = 0.0
        while self._spent_last_minute(self.clock()) + cost > self.per_minute:
            pause = 60 - (self.clock() - self._window[0][0]) + 0.05
            if waited + pause > self.max_wait_seconds:
                raise QuotaExhausted("per-minute credits used and the wait limit is reached")
            self.sleep(pause)
            waited += pause
        self._window.append((self.clock(), cost))
        self.used += cost


@dataclass
class RequestCache:
    """Process-memory dedupe of identical requests, for at most one bar interval."""
    clock: Callable[[], float] = time.monotonic
    _items: dict = field(default_factory=dict)

    def get(self, key: tuple, interval: str) -> Any:
        hit = self._items.get(key)
        if hit and self.clock() - hit[0] < INTERVAL_SECONDS.get(interval, 60):
            return hit[1]
        self._items.pop(key, None)
        return None

    def put(self, key: tuple, value: Any) -> None:
        self._items[key] = (self.clock(), value)


def is_credit_error(payload: Any) -> bool:
    """Twelve Data answers 429 (and the message names API credits) when they run out."""
    if not isinstance(payload, dict) or payload.get("status") != "error":
        return False
    return payload.get("code") == 429 or "credits" in str(payload.get("message", "")).lower()


def guarded_fetch(fetch: Callable[[], Any], *, key: tuple, interval: str, symbols: int, endpoint: str,
                  guard: CreditGuard, cache: RequestCache) -> Any:
    """One request through the cache and the guard; an exhausted answer raises QuotaExhausted."""
    cached = cache.get(key, interval)
    if cached is not None:
        return cached
    guard.acquire(symbols * ENDPOINT_COST[endpoint])
    payload = fetch()
    if is_credit_error(payload):
        raise QuotaExhausted(str(payload.get("message", "Twelve Data credits exhausted"))[:200])
    cache.put(key, payload)
    return payload
