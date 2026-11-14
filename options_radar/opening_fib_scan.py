"""Opening-range Fibonacci research scanner; no orders and no options quotes.

All bars must be completed, from the SAME explicitly declared feed. This module
never fetches data, stores licensed prices, or sends any Telegram messages.
"""
from __future__ import annotations

import html
import math
from datetime import datetime, timedelta, timezone
from typing import Any

BAR = timedelta(minutes=5)
PROVIDER_DELAY = timedelta(minutes=16)
FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _valid(b: Any) -> bool:
    if not isinstance(b, dict) or not isinstance(b.get("t"), datetime) or b["t"].tzinfo is None:
        return False
    vals = [b.get(k) for k in ("o", "h", "l", "c", "v")]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in vals):
        return False
    o, h, l, c, v = vals
    return 0 < l <= min(o, c) <= max(o, c) <= h and v >= 0


def _empty(symbol: str, reason: str) -> dict[str, Any]:
    return {"symbol": symbol, "state": "NO_DATA", "reason": reason}


def evaluate(
    symbol: str,
    raw: list[dict[str, Any]],
    *,
    session_open: datetime,
    now: datetime,
    feed: str,
) -> dict[str, Any]:
    """Pure deterministic scanner; anchor precisely to the 09:30-09:45 session.

    State is WATCH_CALL/WATCH_PUT/WAIT/NO_DATA. Even a WATCH is not a live
    order: Basic-plan source bars are at least 16 minutes delayed.
    """
    if session_open.tzinfo is None or now.tzinfo is None:
        raise ValueError("Timezone-aware clock required")
    if feed not in {"sip", "iex"}:
        return _empty(symbol, "مصدر غير معروف")
    cutoff = now.astimezone(timezone.utc) - PROVIDER_DELAY
    open_utc = session_open.astimezone(timezone.utc)
    if open_utc + timedelta(minutes=25) > cutoff:
        return _empty(symbol, "بيانات أول فترة لم تنضج بعد")
    chosen = {}
    for bar in raw:
        if not _valid(bar):
            continue
        stamp = bar["t"].astimezone(timezone.utc)
        if stamp < open_utc or stamp + BAR > cutoff:
            continue
        if stamp in chosen:
            return _empty(symbol, "شموع مكررة")
        chosen[stamp] = bar

    starts = [open_utc + BAR * i for i in range(3)]
    if any(t not in chosen for t in starts):
        return _empty(symbol, "شمعة افتتاح ناقصة (يلزم 3×5 دقائق)")
    first = [chosen[t] for t in starts]
    high, low = max(x["h"] for x in first), min(x["l"] for x in first)
    width = high - low
    midpoint = (high + low) / 2
    if width <= 0 or not 0.0012 <= width / midpoint <= 0.06:
        return {"symbol": symbol, "state": "WAIT", "reason": "نطاق افتتاح ضيق جدًا أو استثنائي"}

    opening_direction = "صاعدة" if first[-1]["c"] > first[0]["o"] else "هابطة"
    fib = {str(r): round(high - width * r if opening_direction == "صاعدة"
                         else low + width * r, 4) for r in FIB_RATIOS}
    post = [chosen[t] for t in sorted(chosen)
            if open_utc + timedelta(minutes=15) <= t < open_utc + timedelta(minutes=90)]
    base = {
        "symbol": symbol, "state": "WAIT", "feed": feed,
        "opening_high": high, "opening_low": low, "midpoint": midpoint,
        "fib": fib, "opening_direction": opening_direction,
        "source_last_bar": post[-1]["t"].isoformat() if post else None,
        "reason": "انتظار تأكيد بعد الافتتاح",
    }
    if len(post) < 2:
        return base
    last = post[-2:]
    # Do not mistake two historical bars separated by a liquidity gap for
    # consecutive confirmation candles, or signal from a stale ticker.
    if last[1]["t"] - last[0]["t"] != BAR:
        return {**base, "reason": "فجوة في شموع التأكيد"}
    if cutoff - (last[-1]["t"].astimezone(timezone.utc) + BAR) > timedelta(minutes=20):
        return {**base, "reason": "آخر شمعة تأكيد قديمة"}
    closes = [b["c"] for b in last]
    side = ("CALL" if min(closes) > high else
            "PUT" if max(closes) < low else None)
    if side is None:
        return {**base, "reason": "لا يوجد اختراق مؤكد بإغلاقين"}
    entry = closes[-1]  # delayed observation, not a live executable quote
    if side == "CALL":
        stop = high - 0.25 * width
        targets = [high + width * ratio for ratio in (0.272, 0.618, 1.0)]
        risk = entry - stop
        reward2 = targets[1] - entry
        chasing = entry >= targets[0]
    else:
        stop = low + 0.25 * width
        targets = [low - width * ratio for ratio in (0.272, 0.618, 1.0)]
        risk = stop - entry
        reward2 = entry - targets[1]
        chasing = entry <= targets[0]
    if risk <= 0 or chasing or reward2 / risk < 1.5:
        return {**base, "reason": "سعر متأخر عن هدف أول أو العائد/المخاطرة غير كاف"}
    return {
        **base, "state": "WATCH_" + side,
        "entry_observed_delayed": round(entry, 4),
        "trigger": round(high if side == "CALL" else low, 4),
        "stop": round(stop, 4),
        "targets": [round(t, 4) for t in targets],
        "rr2": round(reward2 / risk, 2),
        "reason": "إغلاقان متتاليان خارج نطاق الافتتاح؛ متابعة فقط",
    }


def render_private_digest(results: list[dict[str, Any]], *,
                          session_date: str, limit: int = 5) -> str:
    """One short owner-only Telegram message. No redistribution/public output."""
    states = {"WATCH_CALL": [], "WATCH_PUT": [], "WAIT": [], "NO_DATA": []}
    for item in results:
        states.get(str(item.get("state")), states["NO_DATA"]).append(item)
    picks = sorted(states["WATCH_CALL"] + states["WATCH_PUT"],
                   key=lambda x: (-float(x.get("rr2", 0)), x["symbol"]))[:limit]
    lines = [
        f"<b>غازي رادار | فيبوناتشي افتتاح {html.escape(session_date)}</b>",
        "المرجع 9:30–9:45 نيويورك | فريم 15 دقيقة",
        f"المفحوص {len(results)} | مراقبة كول {len(states['WATCH_CALL'])} | "
        f"مراقبة بوت {len(states['WATCH_PUT'])} | انتظار {len(states['WAIT'])} | "
        f"بيانات ناقصة {len(states['NO_DATA'])}",
        "⚠️ الشموع متأخرة 16 دقيقة أو أكثر؛ هذه مناطق بحث وليست أسعار تنفيذ أو عقود خيارات.",
    ]
    if picks:
        lines.append("<b>أبرز فرص المراقبة (ليست صفقات منفذة):</b>")
    else:
        lines.append("لا توجد فرصة اجتازت شروط التأكيد والعائد/المخاطرة حتى وقت الفحص.")
    for item in picks:
        symbol = html.escape(item["symbol"])
        side = "كول" if item["state"] == "WATCH_CALL" else "بوت"
        ts = html.escape(str(item.get("source_last_bar") or "?")[:16])
        targets = " / ".join(f"{p:.2f}" for p in item["targets"])
        lines.append(
            f"<b>{symbol} — مراقبة {side}</b> | R2 {item['rr2']:.2f}\n"
            f"الاختراق {item['trigger']:.2f} | إغلاق مرصود {item['entry_observed_delayed']:.2f}\n"
            f"وقف {item['stop']:.2f} | أهداف {targets}\n"
            f"آخر شمعة مصدر {ts} UTC | تغطية {html.escape(item['feed'].upper())}"
        )
    # Every configured symbol gets a status; minimize Telegram noise.
    for state, label in [("WATCH_CALL", "كول"), ("WATCH_PUT", "بوت"),
                         ("WAIT", "انتظار"), ("NO_DATA", "غير مكتمل")]:
        names = ", ".join(html.escape(x["symbol"]) for x in states[state])
        if names:
            lines.append(f"<b>{label} ({len(states[state])}):</b> {names}")
    lines.append("لا توجد احتمالات نجاح مثبتة؛ طابق السعر المباشر وسيولة العقد قبل أي تداول.")
    while len("\n".join(lines)) > 3900 and len(lines) > 5:
        # Shorten the longest status list, but never cut an HTML tag/number.
        idx = max(range(4, len(lines) - 1), key=lambda i: len(lines[i]))
        candidate = lines[idx]
        if "," in candidate and "<b>" in candidate:
            head, _, body = candidate.partition("</b> ")
            names = body.split(", ")
            if len(names) > 8:
                lines[idx] = head + "</b> " + ", ".join(names[:8]) + f" ... ({len(names)-8} أخرى)"
                continue
        lines.pop(idx)
    return "\n".join(lines)[:3900]
