"""Closed-bar, non-repainting liquidity/market-structure research.

Inspired by the detection/provenance *principles* in MIT projects
kayasolomon/poi-liquidity-detector and joshyattridge/smart-money-concepts.
Independent, minimal Python implementation. No source fetching, brokerage
or publishing. A wick sweep is a PRICE-ACTION PROXY; it never proves stop
orders, institutional flows, hidden liquidity or dealer positioning.

Events are emitted only when the final required five-minute bar closes.
Confirmed pivots become eligible after `right` FUTURE bars have already
closed (and never at the pivot bar), so replaying a truncated prefix gives
exactly the same known-at-index events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from options_radar.core_options_strategy import ohlcv, _ema

NY = ZoneInfo("America/New_York")
MIN_CURRENT_BARS = 26
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
RETEST_WINDOW = 12
VOLUME_CONFIRMATION_RATIO = 1.5


def _trend(closes: list[float]) -> str:
    fast, slow = _ema(closes, 9), _ema(closes, 21)
    if fast is None or slow is None:
        return "INSUFFICIENT"
    if fast > slow and closes[-1] > fast:
        return "UP"
    if fast < slow and closes[-1] < fast:
        return "DOWN"
    return "MIXED"


def _fifteen_from_five(session: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for bar in session:
        date = bar["time"].astimezone(NY)
        floor = date.replace(minute=date.minute // 15 * 15, second=0, microsecond=0)
        buckets.setdefault(floor, []).append(bar)
    result = []
    for start, bars in sorted(buckets.items()):
        if len(bars) != 3:
            continue
        rows = sorted(bars, key=lambda x: x["time"])
        if any(rows[i]["time"] != rows[0]["time"] + timedelta(minutes=5 * i)
               for i in range(3)):
            continue
        if rows[0]["time"].astimezone(NY) != start:
            continue
        result.append({"start": start.isoformat(), "close": rows[-1]["close"]})
    return result


def _base(status: str) -> dict[str, Any]:
    return {
        "schema": "ghazi.structure_liquidity_shadow.v1",
        "status": status, "research_only": True,
        "execution_authority": False, "option_quote_verified": False,
        "actual_order_flow_verified": False, "liquidation_or_stops_observed": False,
        "repaint_policy": "CONFIRMED_COMPLETED_5M_ONLY",
        "swing_confirmation_lag_bars": PIVOT_RIGHT,
        "direction": "WAIT", "signal": "WAIT",
        "trend_5m": "INSUFFICIENT", "trend_15m": "INSUFFICIENT",
        "research_confluence_count": 0, "win_probability": None,
        "signal_events": [], "last_completed_5m": None,
        "interpretation": "OHLCV_PRICE_ACTION_PROXY_NOT_ORDER_BOOK",
    }


def analyze(rows: Any, *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    bars = ohlcv(rows, now=now, minutes=5)
    if not bars:
        return _base("NO_COMPLETED_BARS")
    last_day = bars[-1]["time"].astimezone(NY).date()
    session = [x for x in bars if x["time"].astimezone(NY).date() == last_day]
    if len(session) < MIN_CURRENT_BARS:
        return _base("INSUFFICIENT_COMPLETED_BARS")
    # Even one hole invalidates the pattern path: skipped bars may change
    # swings, volume ratios, 15m alignment, and the entry/exit chronology.
    if any(session[i]["time"] != session[i-1]["time"] + timedelta(minutes=5)
           for i in range(1, len(session))):
        return _base("INCOMPLETE_INTRADAY_BAR_SEQUENCE")

    out = _base("RESEARCH_ONLY")
    out["last_completed_5m"] = (
        session[-1]["time"] + timedelta(minutes=5)).isoformat()
    five = [x["close"] for x in session]
    fifteen = _fifteen_from_five(session)
    out["trend_5m"] = _trend(five)
    out["trend_15m"] = _trend([x["close"] for x in fifteen])
    if out["trend_5m"] == out["trend_15m"] and out["trend_5m"] in ("UP", "DOWN"):
        out["direction"] = out["trend_5m"]
        out["research_confluence_count"] += 1

    hi_pivot = None
    lo_pivot = None
    pending_high = None
    pending_low = None
    broken_direction = None
    events = []

    def emit(kind: str, i: int, pivot: dict | None = None, *, volume_confirmed: bool = False):
        event = {
            "kind": kind, "known_at_index": i,
            "known_at_close": (session[i]["time"] + timedelta(minutes=5)).isoformat(),
            "pivot_known_at_index": pivot["known_at"] if pivot else None,
            "volume_proxy_confirmed": volume_confirmed,
            "execution_authority": False,
        }
        events.append(event)

    for i, bar in enumerate(session):
        prev = session[i-1]["close"] if i else bar["open"]
        high = hi_pivot
        low = lo_pivot
        volume_reference = (
            mean(x["volume"] for x in session[i-20:i]) if i >= 20 else None)
        volume_ok = bool(volume_reference is not None and volume_reference > 0
                         and bar["volume"] >= VOLUME_CONFIRMATION_RATIO * volume_reference)
        atr = (mean(x["high"] - x["low"] for x in session[i-14:i])
               if i >= 14 else None)
        tolerance = (atr * .05 if atr is not None and atr > 0 else None)

        # If one five-minute candle pierces both extremes, the OHLCV candle
        # does not reveal which price was visited first: suppress a direction.
        sweep_high = bool(
            high and not high["used"] and tolerance is not None
            and bar["high"] > high["price"] + tolerance
            and bar["close"] < high["price"] and prev <= high["price"])
        sweep_low = bool(
            low and not low["used"] and tolerance is not None
            and bar["low"] < low["price"] - tolerance
            and bar["close"] > low["price"] and prev >= low["price"])
        if sweep_high and sweep_low:
            high["used"] = low["used"] = True
            pending_high = pending_low = None
            emit("AMBIGUOUS_BOTH_SIDES_WICKED", i)
        elif sweep_high:
            high["used"] = True
            pending_high = i
            pending_low = None
            emit("HIGH_SWEEP_PRICE_PROXY", i, high, volume_confirmed=volume_ok)
        elif sweep_low:
            low["used"] = True
            pending_low = i
            pending_high = None
            emit("LOW_SWEEP_PRICE_PROXY", i, low, volume_confirmed=volume_ok)

        # Only the *close* across a previously confirmed opposing swing
        # confirms a structural break. Same-bar sweep + break is ambiguous.
        cross_up = bool(high and prev <= high["price"] < bar["close"])
        cross_down = bool(low and prev >= low["price"] > bar["close"])
        if cross_up and not cross_down:
            if (pending_low is not None and i > pending_low
                    and i - pending_low <= RETEST_WINDOW):
                emit("LOW_SWEEP_THEN_UP_STRUCTURAL_BREAK", i, high,
                     volume_confirmed=volume_ok)
                pending_low = None
            if broken_direction != "UP":
                emit("CHOCH_UP" if broken_direction == "DOWN" else "STRUCTURE_BREAK_UP",
                     i, high, volume_confirmed=volume_ok)
            broken_direction = "UP"
            high["used"] = True
        elif cross_down and not cross_up:
            if (pending_high is not None and i > pending_high
                    and i - pending_high <= RETEST_WINDOW):
                emit("HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK", i, low,
                     volume_confirmed=volume_ok)
                pending_high = None
            if broken_direction != "DOWN":
                emit("CHOCH_DOWN" if broken_direction == "UP" else "STRUCTURE_BREAK_DOWN",
                     i, low, volume_confirmed=volume_ok)
            broken_direction = "DOWN"
            low["used"] = True

        if pending_high is not None and i - pending_high > RETEST_WINDOW:
            pending_high = None
        if pending_low is not None and i - pending_low > RETEST_WINDOW:
            pending_low = None

        # A pivot at j can be used only from the NEXT candle after its
        # confirmation at i, so no current-bar self-confirmation.
        j = i - PIVOT_RIGHT
        if j >= PIVOT_LEFT:
            p = session[j]
            left = session[j-PIVOT_LEFT:j]
            right = session[j+1:i+1]
            if all(p["high"] > x["high"] for x in (*left, *right)):
                hi_pivot = {"price": p["high"], "known_at": i, "used": False}
            if all(p["low"] < x["low"] for x in (*left, *right)):
                lo_pivot = {"price": p["low"], "known_at": i, "used": False}

    out["signal_events"] = events
    recent = [x for x in events if len(session) - 1 - x["known_at_index"] <= 3]
    priority = (
        "HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK", "LOW_SWEEP_THEN_UP_STRUCTURAL_BREAK",
        "HIGH_SWEEP_PRICE_PROXY", "LOW_SWEEP_PRICE_PROXY",
        "CHOCH_UP", "CHOCH_DOWN",
    )
    for kind in priority:
        if any(event["kind"] == kind for event in recent):
            out["signal"] = kind
            out["research_confluence_count"] += 1
            break

    # A research confluence score is a count of descriptive observations,
    # not a calibrated probability of win or proof of options liquidity.
    return out
