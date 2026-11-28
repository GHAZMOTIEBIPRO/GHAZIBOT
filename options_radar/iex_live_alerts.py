"""Real-time first-look alerts from the Alpaca IEX minute-bar stream (pure logic; the runner does I/O).

IEX is ONE venue: an IEX bar is real time but partial (a few % of U.S. volume), so every alert says
"رصد أولي IEX — تغطية جزئية". It never replaces the SIP-based stages (options_radar.session_tracker),
which still decide CONFIRMED and target/invalidation states 16 minutes later on consolidated bars.

Rule (the V5 rule of the 1-minute study, measured here on the same feed type): a completed 5-minute
bucket (session-aligned) closing beyond the map trigger with IEX volume >= RVOL_MIN x the mean IEX
volume of that slot over the prior sessions. One alert per symbol and side per day. Levels come from
the pre-open map (prior completed session) and are never changed intraday.
Latency = alert decision time - bucket end, in seconds (reported as p50/p95).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any

RVOL_MIN = 1.5


@dataclass
class LiveState:
    open_at: datetime
    levels: dict[str, dict[str, float]]            # symbol -> {"call": trigger, "put": trigger}
    baseline: dict[str, dict[int, float]]          # symbol -> {5m slot index: mean IEX volume}
    minutes: dict[str, dict[int, dict]] = field(default_factory=dict)
    fired: set[tuple[str, str]] = field(default_factory=set)
    latencies: list[float] = field(default_factory=list)

    def on_bar(self, symbol: str, start: datetime, o: float, h: float, l: float, c: float, v: float,
               received_at: datetime) -> list[dict[str, Any]]:
        """Feed one IEX minute bar; returns alerts completed by it (usually none)."""
        minute = int((start - self.open_at).total_seconds() // 60)
        if minute < 0 or symbol not in self.levels:
            return []
        bars = self.minutes.setdefault(symbol, {})
        bars[minute] = {"o": o, "h": h, "l": l, "c": c, "v": v}
        if (minute + 1) % 5:
            return []  # the 5-minute bucket is not complete yet
        slot = minute // 5
        group = [bars.get(m) for m in range(slot * 5, slot * 5 + 5)]
        if any(b is None for b in group):
            return []  # a missing IEX minute (no trades on IEX): the bucket is not trusted
        close, volume = group[-1]["c"], sum(b["v"] for b in group)
        end = self.open_at + timedelta(minutes=(slot + 1) * 5)
        base = (self.baseline.get(symbol) or {}).get(slot)
        out = []
        for side, trigger in self.levels[symbol].items():
            beyond = close > trigger if side == "call" else close < trigger
            if not beyond or (symbol, side) in self.fired or not base or volume < RVOL_MIN * base:
                continue
            self.fired.add((symbol, side))
            latency = (received_at - end).total_seconds()
            self.latencies.append(latency)
            out.append({"symbol": symbol, "side": side.upper(), "trigger": trigger, "close": close,
                        "rvol_iex": round(volume / base, 2), "bucket_end": end.isoformat(),
                        "latency_s": round(latency, 1), "feed": "IEX (partial, real time)"})
        return out

    def latency_summary(self) -> dict[str, Any]:
        xs = sorted(self.latencies)
        if not xs:
            return {"alerts": 0}
        p95 = xs[min(len(xs) - 1, round(0.95 * (len(xs) - 1)))]
        return {"alerts": len(xs), "p50_s": round(median(xs), 1), "p95_s": round(p95, 1), "max_s": round(xs[-1], 1)}


def baseline_from_bars(bars_5m: list[dict[str, Any]], sessions: list[tuple[datetime, datetime]]) -> dict[int, float]:
    """Mean IEX volume per 5-minute slot over the given prior sessions (same feed as the live bars)."""
    slots: dict[int, list[float]] = {}
    for o, c in sessions:
        for b in bars_5m:
            if o <= b["t"] < c:
                slots.setdefault(int((b["t"] - o).total_seconds() // 300), []).append(b["v"])
    return {i: sum(v) / len(v) for i, v in slots.items() if v}
