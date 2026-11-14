"""Offline, deterministic delayed-data replay for the opening Fibonacci scanner.

No network or licensed-price publication. This is a *test harness*, not a
performance claim. Decisions see only bars available by the 16-minute cutoff,
and fills use the first future bar after the alert, never the stale signal
price. Within-bar stop/target ambiguity is resolved pessimistically.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .opening_fib_scan import evaluate, _valid, BAR


def replay_session(
    symbol: str,
    bars: list[dict[str, Any]],
    *,
    session_open: datetime,
    session_close: datetime,
    feed: str = "sip",
    notices_minutes: tuple[int, ...] = (57, 72),
    min_opening_notional: float = 1_000_000,
    cost_per_share_roundtrip: float = 0.02,
) -> dict[str, Any]:
    """Return the outcome of at most one hypothetical trade in one session."""
    if (session_open.tzinfo is None or session_close.tzinfo is None
            or session_close <= session_open):
        raise ValueError("aware valid session boundaries required")
    if cost_per_share_roundtrip < 0:
        raise ValueError("cost cannot be negative")
    rows = sorted((b for b in bars if _valid(b)), key=lambda b: b["t"])
    if len({b["t"] for b in rows}) != len(rows):
        return {"symbol": symbol, "status": "INVALID_DUPLICATE_BARS"}
    for minute in notices_minutes:
        alert_time = session_open + timedelta(minutes=minute)
        if alert_time >= session_close:
            continue
        signal = evaluate(
            symbol, rows, session_open=session_open, now=alert_time,
            feed=feed, min_opening_notional=min_opening_notional,
        )
        if signal["state"] not in ("WATCH_CALL", "WATCH_PUT"):
            continue
        future = [b for b in rows if alert_time <= b["t"] and
                  b["t"] + BAR <= session_close]
        if not future:
            return {"symbol": symbol, "status": "UNFILLED"}
        first = future[0]
        entry = first["o"]  # next observed open after broadcast, never stale close
        side = 1 if signal["state"] == "WATCH_CALL" else -1
        stop, target1, target2 = signal["stop"], *signal["targets"][:2]
        risk = side * (entry - stop)
        reward = side * (target2 - entry)
        if risk <= 0 or side * (target1 - entry) <= 0 or reward / risk < 1.5:
            return {"symbol": symbol, "status": "SKIPPED_LATE_FILL"}
        exit_price, event = future[-1]["c"], "EXPIRED"
        for candle in future:
            hit_stop = candle["l"] <= stop if side == 1 else candle["h"] >= stop
            hit_target = candle["h"] >= target2 if side == 1 else candle["l"] <= target2
            # Pessimism: if both hit inside one OHLC candle, record the stop.
            if hit_stop:
                exit_price, event = stop, "LOSS"
                break
            if hit_target:
                exit_price, event = target2, "WIN"
                break
        r_net = (
            side * (exit_price - entry) - cost_per_share_roundtrip
        ) / risk
        return {
            "symbol": symbol,
            "status": event,
            "net_r": round(r_net, 4),
            "alert_time_utc": alert_time.astimezone(timezone.utc).isoformat(),
            "fill_time_utc": first["t"].astimezone(timezone.utc).isoformat(),
            "research_only": True,
        }
    return {"symbol": symbol, "status": "NO_TRADE", "research_only": True}
