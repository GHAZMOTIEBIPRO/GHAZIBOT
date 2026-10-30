"""GHAZI CORE Ω — source-stamped, fail-closed index/mega-cap strategy research.

All observations are input evidence, not simulated orders. An indicative option
feed can NEVER produce an execution-authorized CALL/PUT. "Gamma exposure" is
only a signed OI*gamma model proxy, not dealer positioning or a gamma flip.
This module has no network, publishing, account actions, or hidden fallbacks.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
CORE = frozenset(("SPY", "QQQ", "TSLA", "AMD", "MU", "NVDA", "MSFT",
                  "BABA", "GOOG", "GOOGL", "META"))
MIN_INTRADAY = 26


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, OverflowError):
        return None


def ohlcv(rows: Any, *, now: datetime, minutes: int | None) -> list[dict[str, Any]]:
    """Accept only timestamped, plausible, *finished* source bars."""
    if not isinstance(rows, list) or now.tzinfo is None:
        return []
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = stamp(row.get("timestamp") or row.get("t"))
        raw = [number(row.get(k, row.get(short))) for k, short in (
            ("open", "o"), ("high", "h"), ("low", "l"),
            ("close", "c"), ("volume", "v"))]
        if t is None or any(n is None for n in raw):
            continue
        o, h, l, c, v = raw
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c):
            continue
        if minutes is not None:
            local = t.astimezone(NY)
            if (local.hour, local.minute) < (9, 30) or (local.hour, local.minute) >= (16, 0):
                continue
            if t + timedelta(minutes=minutes) > now.astimezone(timezone.utc):
                continue
        elif t > now.astimezone(timezone.utc):
            continue
        result[t] = {"time": t, "open": o, "high": h, "low": l,
                     "close": c, "volume": v}
    return [result[key] for key in sorted(result)]


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    x = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for value in values[period:]:
        x += alpha * (value - x)
    return x


def technical_levels(
    symbol: str, daily: list[dict], bars5: list[dict], *, now: datetime,
) -> dict[str, Any]:
    daily = ohlcv(daily, now=now, minutes=None)
    bars5 = ohlcv(bars5, now=now, minutes=5)
    day = now.astimezone(NY).date()
    # Daily bars represent the *start* of the session and must not be used
    # as completed until the following NY calendar day.
    complete = [row for row in daily if row["time"].astimezone(NY).date() < day]
    current = [row for row in bars5 if row["time"].astimezone(NY).date() == day]
    prior = complete[-1] if complete else None
    if not prior or len(current) < MIN_INTRADAY:
        return {"symbol": symbol, "status": "INSUFFICIENT_COMPLETED_BARS",
                "decision": "WAIT", "levels": {}}
    opening = [r for r in current if (9, 30) <= (
        r["time"].astimezone(NY).hour, r["time"].astimezone(NY).minute) < (10, 0)]
    if len(opening) < 6:
        return {"symbol": symbol, "status": "OPENING_RANGE_INCOMPLETE",
                "decision": "WAIT", "levels": {}}
    traded = sum(r["volume"] for r in current)
    vwap = (sum(((r["high"] + r["low"] + r["close"]) / 3) * r["volume"] for r in current)
            / traded) if traded > 0 else None
    prices = [r["close"] for r in current]
    fast, slow = _ema(prices, 9), _ema(prices, 21)
    or_high, or_low = max(x["high"] for x in opening), min(x["low"] for x in opening)
    last = prices[-1]
    week = complete[-5:]
    week_hi = max(x["high"] for x in week)
    week_lo = min(x["low"] for x in week)
    levels = {"previous_day_high": round(prior["high"], 4),
              "previous_day_low": round(prior["low"], 4),
              "previous_week_5session_high": round(week_hi, 4),
              "previous_week_5session_low": round(week_lo, 4),
              "opening_range_30m_high": round(or_high, 4),
              "opening_range_30m_low": round(or_low, 4),
              "vwap_5m_iex": round(vwap, 4) if vwap else None,
              "last_completed_5m_close": round(last, 4)}
    direction = "WAIT"
    if fast is not None and slow is not None and vwap:
        if last > or_high and last > vwap and fast > slow:
            direction = "CALL"
        elif last < or_low and last < vwap and fast < slow:
            direction = "PUT"
    # Source IEX has only one exchange's trades; do not call its volume
    # complete-market volume, and do not confirm a broker-fill price.
    return {"symbol": symbol, "status": "RESEARCH_ONLY_IEX",
            "decision": direction, "levels": levels,
            "source": "ALPACA_IEX_5M_AND_DAILY",
            "source_scope": "IEX_PARTIAL_EXCHANGE_NOT_SIP",
            "last_bar_end": (current[-1]["time"] + timedelta(minutes=5)).isoformat(),
            "completed_5m_count": len(current),
            "day_five_minute_volume_iex": int(traded),
            "execution_authority": False}


def _quote_info(quote: Any, now: datetime) -> dict[str, Any]:
    if not isinstance(quote, dict):
        return {"valid": False, "block": "MISSING_BID_ASK"}
    bid = number(quote.get("bid_price"))
    ask = number(quote.get("ask_price"))
    t = stamp(quote.get("timestamp"))
    if t is None or bid is None or ask is None or bid <= 0 or ask <= bid:
        return {"valid": False, "block": "INVALID_BID_ASK"}
    age = (now.astimezone(timezone.utc) - t).total_seconds()
    if age < 0 or age > 180:
        return {"valid": False, "block": "QUOTE_STALE_OR_FUTURE"}
    spread = (ask - bid) / ask
    return {"valid": True, "bid": bid, "ask": ask,
            "spread_pct_of_ask": spread, "age_seconds": round(age, 1),
            "bid_size": number(quote.get("bid_size")),
            "ask_size": number(quote.get("ask_size"))}


def gamma_proxy(contracts: list[dict], *, spot: float, asof: datetime) -> dict[str, Any]:
    """Partial-chain GEX proxy: call-positive/put-negative *assumed* signs."""
    by_strike: dict[float, dict[str, float]] = defaultdict(
        lambda: {"call": 0.0, "put": 0.0})
    eligible = 0
    has_greeks = 0
    has_oi = 0
    for row in contracts:
        gamma = number(row.get("gamma"))
        oi = number(row.get("open_interest"))
        strike = number(row.get("strike"))
        side = str(row.get("type") or "").lower()
        oi_date = row.get("open_interest_date")
        try:
            oi_age = (asof.date() - date.fromisoformat(str(oi_date))).days
        except (ValueError, TypeError):
            oi_age = 999
        if gamma is not None and gamma > 0:
            has_greeks += 1
        if oi is not None and oi > 0 and 0 <= oi_age <= 4:
            has_oi += 1
        if (side not in ("call", "put") or strike is None or strike <= 0
                or gamma is None or gamma <= 0 or oi is None or oi <= 0
                or not 0 <= oi_age <= 4):
            continue
        eligible += 1
        by_strike[strike][side] += gamma * oi * 100 * spot * spot * 0.01
    total = len(contracts)
    coverage = round(eligible / total, 3) if total else 0
    # Without sufficient expiry/strike coverage this cannot be a trustworthy
    # wall. Do not label a 10-contract slice as "institutional gamma."
    reliable = total >= 20 and coverage >= 0.7
    call_wall = (max(by_strike, key=lambda s: by_strike[s]["call"])
                 if reliable and by_strike and any(v["call"] > 0 for v in by_strike.values())
                 else None)
    put_wall = (max(by_strike, key=lambda s: by_strike[s]["put"])
                if reliable and by_strike and any(v["put"] > 0 for v in by_strike.values())
                else None)
    return {"status": "PARTIAL_GEX_RESEARCH" if reliable else "INSUFFICIENT_GEX_COVERAGE",
            "eligible_contracts": eligible, "total_contracts": total,
            "oi_coverage": round(has_oi / total, 3) if total else 0,
            "gamma_coverage": round(has_greeks / total, 3) if total else 0,
            "joint_coverage": coverage,
            "call_wall": call_wall, "put_wall": put_wall,
            "dealer_position_verified": False,
            "gamma_flip_verified": False,
            "signed_positioning_is_assumption": True}


def rank_contracts(
    symbol: str, side: str, contracts: list[dict],
    *, spot: float, now: datetime, feed: str = "indicative",
) -> dict[str, Any]:
    if side not in ("CALL", "PUT"):
        return {"status": "NO_DIRECTION", "candidates": [], "execution_ready": False}
    ranked = []
    for c in contracts:
        code = str(c.get("symbol") or "")
        if not OCC.fullmatch(code) or c.get("type") != side.lower():
            continue
        try:
            dte = (date.fromisoformat(str(c["expiration"])) - now.astimezone(NY).date()).days
        except (KeyError, ValueError, TypeError):
            continue
        if dte < 1 or dte > (7 if symbol in ("SPY", "QQQ") else 21):
            continue
        strike, oi = number(c.get("strike")), number(c.get("open_interest"))
        delta, gamma = number(c.get("delta")), number(c.get("gamma"))
        if strike is None or spot <= 0 or abs(strike / spot - 1) > 0.1:
            continue
        quote = _quote_info(c.get("latest_quote"), now)
        if not quote["valid"]:
            continue
        if delta is None or not .25 <= abs(delta) <= .65:
            continue
        if oi is None or oi < 200 or quote["spread_pct_of_ask"] > .12:
            continue
        try:
            oi_date = date.fromisoformat(str(c["open_interest_date"]))
            oi_age = (now.astimezone(NY).date() - oi_date).days
        except (KeyError, TypeError, ValueError):
            continue
        if oi_age < 0 or oi_age > 4:
            continue
        # Indicative prices and unknown contract volume are not execution
        # evidence even if open-interest / spread look attractive.
        volume = number(c.get("volume"))
        blockers = []
        if volume is None:
            blockers.append("CONTRACT_TODAY_VOLUME_UNVERIFIED")
        elif volume < 200:
            blockers.append("LOW_REPORTED_OPTION_VOLUME")
        if feed != "opra":
            blockers.append("INDICATIVE_FEED_NOT_EXECUTION_OPRA")
        if not c.get("open_interest_date"):
            blockers.append("OPEN_INTEREST_DATE_MISSING")
        score = 35 * (1 - min(abs(abs(delta) - .45) / .45, 1))
        score += 25 * (1 - min(quote["spread_pct_of_ask"] / .12, 1))
        score += 20 * min(oi / 1500, 1)
        score += 20 * (1 - min(abs(strike / spot - 1) / .1, 1))
        ranked.append({"contract_symbol": code, "side": side,
                       "expiration": c["expiration"], "strike": strike,
                       "delta": delta, "gamma": gamma,
                       "reported_oi": oi, "reported_volume": volume,
                       "quote": quote, "score_research": round(score, 2),
                       "blockers": blockers, "execution_ready": False})
    ranked.sort(key=lambda x: x["score_research"], reverse=True)
    return {"status": "RESEARCH_CANDIDATES_ONLY" if ranked else "NO_QUALIFIED_SNAPSHOT",
            "candidates": ranked[:3], "execution_ready": False,
            "note": "Snapshot feed and OI are not verified trade aggression or executable liquidity."}


def evaluate(
    symbol: str, *, daily: list[dict], bars5: list[dict],
    chain: list[dict], now: datetime, feed: str = "indicative",
) -> dict[str, Any]:
    """Return research scenario; never produce an execution authorization."""
    sym = symbol.upper().strip()
    if sym not in CORE or now.tzinfo is None:
        return {"symbol": sym, "status": "UNSUPPORTED_OR_NAIVE_TIME",
                "decision": "WAIT", "execution_authority": False}
    levels = technical_levels(sym, daily, bars5, now=now)
    gamma = gamma_proxy(chain, spot=levels.get("levels", {}).get(
        "last_completed_5m_close", 0), asof=now) if chain else {
            "status": "NO_OPTION_CHAIN", "call_wall": None, "put_wall": None,
            "dealer_position_verified": False}
    decision = levels["decision"]
    if decision == "WAIT":
        contract = {"status": "NO_DIRECTION", "candidates": [], "execution_ready": False}
    else:
        contract = rank_contracts(
            sym, decision, chain, spot=levels["levels"]["last_completed_5m_close"],
            now=now, feed=feed)
    return {"schema": "ghazi.core_options_strategy.v1",
            "symbol": sym, "decision_research": decision,
            "technical": levels, "gamma": gamma, "option": contract,
            "options_feed": feed, "market_data_rights": "PRIVATE_INTERNAL_ONLY",
            "public_display_allowed": False, "execution_authority": False,
            "signal_type": "WATCH_RESEARCH_ONLY" if decision != "WAIT" else "WAIT",
            "risk_policy": "No dealer gamma claims, no verified sweeps, no automatic orders."}
