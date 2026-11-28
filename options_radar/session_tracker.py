"""Intraday state of one pre-open map against today's completed bars (pure, no network).

The map's levels come from the prior completed session, so they are fixed for the whole day; the
tracker never redraws them. Stages, each dated by the end of the bar that completed it:
  BREAKOUT_WATCH  a completed 5m close beyond a trigger
  EARLY_ALERT     the same close with volume >= RVOL_MIN x its time-of-day baseline (V5 in the study)
  CONFIRMED       a completed CONFIRM_MINUTES close beyond the trigger
  T1 / T2 / T3    the first touch of each target after the first beyond-trigger close
  INVALIDATED     a touch of the side's invalidation after that first close
A target and the invalidation inside the same 5m bar is AMBIGUOUS (order unknown), never a hit.
Statuses only describe what happened; they are not a recommendation and carry no probability.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

RVOL_MIN = 1.5
CONFIRM_MINUTES = 30  # set from the 1-minute study (docs/ORACLE_PROGRESS.md); 60 was no better and later
STAGE_AR = {"BREAKOUT_WATCH": "مراقبة اختراق", "EARLY_ALERT": "تنبيه مبكر (حجم مرتفع)", "CONFIRMED": "تأكيد",
            "T1": "الهدف الأول", "T2": "الهدف الثاني", "T3": "الهدف الثالث", "INVALIDATED": "إبطال",
            "AMBIGUOUS": "هدف وإبطال في شمعة واحدة (ترتيب غير معروف)"}


def buckets(bars_5m: list[dict[str, Any]], open_at: datetime, minutes: int) -> list[dict[str, Any]]:
    """Completed session-aligned buckets from 5m bars ('t' = start, keys o/h/l/c/v)."""
    groups: dict[int, list[dict[str, Any]]] = {}
    for b in bars_5m:
        idx = int((b["t"] - open_at).total_seconds() // (minutes * 60))
        if idx >= 0:
            groups.setdefault(idx, []).append(b)
    need = minutes // 5
    return [{"idx": i, "end": open_at + timedelta(minutes=(i + 1) * minutes), "h": max(r["h"] for r in g),
             "l": min(r["l"] for r in g), "c": g[-1]["c"], "v": sum(r.get("v", 0) for r in g)}
            for i, g in sorted(groups.items()) if len(g) == need]


def track(m: dict[str, Any], bars_5m: list[dict[str, Any]], open_at: datetime,
          volume_baseline: dict[int, float] | None = None) -> dict[str, Any]:
    """Events for both sides of one map. `volume_baseline[idx]` = mean prior volume of that 5m slot."""
    if m.get("state") in (None, "NO_DATA"):
        return {"symbol": m.get("symbol"), "events": [], "status": "NO_DATA"}
    five = buckets(bars_5m, open_at, 5)
    confirm = buckets(bars_5m, open_at, CONFIRM_MINUTES)
    events: list[dict[str, Any]] = []
    for side, word in (("call", "CALL"), ("put", "PUT")):
        level = m[side]
        trigger, stop = level["trigger"], level["invalidation"]
        beyond = (lambda p, t=trigger: p > t) if side == "call" else (lambda p, t=trigger: p < t)
        first = next((b for b in five if beyond(b["c"])), None)
        if first is None:
            continue
        base = (volume_baseline or {}).get(first["idx"])
        stage = "EARLY_ALERT" if base and first["v"] >= RVOL_MIN * base else "BREAKOUT_WATCH"
        events.append({"side": word, "stage": stage, "at": first["end"].isoformat(), "level": trigger})
        conf = next((b for b in confirm if beyond(b["c"])), None)
        if conf is not None:
            events.append({"side": word, "stage": "CONFIRMED", "at": conf["end"].isoformat(), "level": trigger})
        pending = [(t["name"], t["value"]) for t in level.get("targets") or []]
        for b in (x for x in five if x["end"] > first["end"]):
            touched_stop = b["l"] <= stop if side == "call" else b["h"] >= stop
            hit = [(n, v) for n, v in pending if (b["h"] >= v if side == "call" else b["l"] <= v)]
            if touched_stop and hit:
                events.append({"side": word, "stage": "AMBIGUOUS", "at": b["end"].isoformat(), "level": stop})
                break
            for name, value in hit:
                events.append({"side": word, "stage": name, "at": b["end"].isoformat(), "level": value})
                pending.remove((name, value))
            if touched_stop:
                events.append({"side": word, "stage": "INVALIDATED", "at": b["end"].isoformat(), "level": stop})
                break
    events.sort(key=lambda e: e["at"])
    last = five[-1] if five else None
    return {"symbol": m["symbol"], "events": events, "status": "OK",
            "last_bar_end": last["end"].isoformat() if last else None, "last_close": last["c"] if last else None}


def scorecard(maps: dict[str, dict[str, Any]], tracked: dict[str, dict[str, Any]],
              closes: dict[str, float]) -> dict[str, Any]:
    """Post-close accountability (counts only): what the morning maps said vs what the day did."""
    card = {"maps": 0, "triggered": 0, "confirmed": 0, "t1": 0, "t2": 0, "t3": 0, "invalidated": 0, "ambiguous": 0,
            "watch_calls": 0, "watch_direction_right": 0, "watch_direction_wrong": 0, "no_data": 0}
    for symbol, m in maps.items():
        if m.get("state") in (None, "NO_DATA"):
            card["no_data"] += 1
            continue
        card["maps"] += 1
        stages = {e["stage"] for e in (tracked.get(symbol) or {}).get("events") or []}
        card["triggered"] += bool(stages & {"BREAKOUT_WATCH", "EARLY_ALERT"})
        for key, stage in (("confirmed", "CONFIRMED"), ("t1", "T1"), ("t2", "T2"), ("t3", "T3"),
                           ("invalidated", "INVALIDATED"), ("ambiguous", "AMBIGUOUS")):
            card[key] += stage in stages
        if m["state"] in ("CALL_WATCH", "PUT_WATCH") and closes.get(symbol):
            card["watch_calls"] += 1
            up = closes[symbol] > m["prior_day"]["close"]
            right = up if m["state"] == "CALL_WATCH" else not up
            card["watch_direction_right" if right else "watch_direction_wrong"] += 1
    return card
