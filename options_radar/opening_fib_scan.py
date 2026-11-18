"""Opening-range Fibonacci research scanner; no orders and no options quotes.

All bars must be completed, from the SAME explicitly declared feed. This module
never fetches data, stores licensed prices, or sends any Telegram messages.
"""
from __future__ import annotations

import html
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from . import telegram_ar as ar
from .opening_fib_context import fib_context_lines

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
    min_opening_notional: float = 1_000_000.0,
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
    # A complete SIP tape is essential for meaningful breakout levels. IEX
    # tracks a single venue and can misstate both volume and extremes.
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
        "opening_notional_estimate": round(sum(x["v"] for x in first) * midpoint, 2),
        "fib": fib, "opening_direction": opening_direction,
        "source_last_bar": post[-1]["t"].isoformat() if post else None,
        "reason": "انتظار تأكيد بعد الافتتاح",
    }
    if feed != "sip":
        return {**base, "reason": "IEX تغطية جزئية؛ لا نصدر مراقبة كول/بوت دون SIP مكتملة"}
    if (min_opening_notional > 0 and
            base["opening_notional_estimate"] < min_opening_notional):
        return {**base, "reason": "سيولة افتتاح تقديرية أدنى من الحد المعتمد"}
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


def _pick_block(item: dict[str, Any]) -> list[str]:
    """One opportunity: what was confirmed, where it is invalid, and the measured targets."""
    call = item["state"] == "WATCH_CALL"
    head = (f"🟢 {ar.ticker(item['symbol'])} — مراقبة صعود (كول)" if call
            else f"🔴 {ar.ticker(item['symbol'])} — مراقبة هبوط (بوت)")
    seen = ar.parse_time(item.get("source_last_bar"))
    bar_note = f" (شمعة {ar.clock_ar(seen, ar.NEW_YORK)} نيويورك)" if seen else ""
    targets = " ← ".join(ar.price(p) for p in item["targets"])
    return [
        head,
        f"• تأكد الاختراق {'فوق' if call else 'تحت'}: {ar.price(item['trigger'])}",
        f"• آخر إغلاق مرصود: {ar.price(item['entry_observed_delayed'])}{bar_note}",
        f"• الأهداف: {targets}",
        f"• تُلغى الفكرة {'تحت' if call else 'فوق'}: {ar.price(item['stop'])}",
        f"• العائد مقابل المخاطرة حتى الهدف الثاني: {float(item['rr2']):.2f} مرة",
    ]


def render_private_digest(results: list[dict[str, Any]], *,
                          session_date: str, limit: int = 5,
                          official_context: dict[str, Any] | None = None) -> str:
    """One owner-only Telegram message in plain Arabic. No redistribution/public output.

    Every number is a field computed by evaluate(); the text only labels and explains it.
    """
    states = {"WATCH_CALL": [], "WATCH_PUT": [], "WAIT": [], "NO_DATA": []}
    for item in results:
        states.get(str(item.get("state")), states["NO_DATA"]).append(item)
    picks = sorted(states["WATCH_CALL"] + states["WATCH_PUT"],
                   key=lambda x: (-float(x.get("rr2", 0)), x["symbol"]))[:limit]
    sip = sum(x.get("feed") == "sip" for x in results)
    lines = [
        f"📊 <b>فيبوناتشي الافتتاح — {html.escape(ar.date_ar(session_date))}</b>",
        "السوق الأمريكي · رسالة خاصة بك",
        "🕘 النطاق المرجعي: أول 15 دقيقة من الجلسة (9:30–9:45 ص نيويورك = 5:30–5:45 م الرياض)",
        (f"📋 النتيجة: فُحص {ar.stocks_ar(len(results))} — صعود (كول) {len(states['WATCH_CALL'])}"
         f" · هبوط (بوت) {len(states['WATCH_PUT'])} · انتظار {len(states['WAIT'])}"
         f" · بيانات ناقصة {len(states['NO_DATA'])}"),
        f"مصدر الشموع: الشريط الموحد SIP لـ {sip} من {len(results)}"
        + (f" (مصدر جزئي IEX لـ {sum(x.get('feed') == 'iex' for x in results)})"
           if any(x.get("feed") == "iex" for x in results) else ""),
        "",
    ]
    if picks:
        lines.append("<b>فرص للمراقبة (ليست صفقات منفذة):</b>")
        for item in picks:
            lines.extend(_pick_block(item))
            lines.append("")
    else:
        lines += ["لا يوجد سهم اجتاز شرطي التأكيد والعائد مقابل المخاطرة حتى وقت الفحص.", ""]
    # Officially sourced, dated events stay apart from the price-derived readings.
    if official_context is not None:
        pick_syms = [p["symbol"] for p in picks]
        present = {x["symbol"] for x in results}
        for priority in ("NVDA", "TSLA", "AMD", "AAPL", "SPY", "QQQ"):
            if priority in present and priority not in pick_syms:
                pick_syms.append(priority)
        pick_syms.extend(x["symbol"] for x in results if x["symbol"] not in pick_syms)
        lines.extend(fib_context_lines(official_context, symbols=pick_syms, limit=3))
        sources = official_context.get("sources") if isinstance(official_context, dict) else {}
        if isinstance(sources, dict):
            available = sum(v == "AVAILABLE" for v in sources.values())
            lines.append(f"مصادر الأخبار الرسمية المتاحة: {available} من {len(sources)} (غياب الخبر لا يعني عدم وجوده).")
        lines.append("")
    for state, label in [("WATCH_CALL", "🟢 صعود"), ("WATCH_PUT", "🔴 هبوط"),
                         ("WAIT", "⏸️ انتظار"), ("NO_DATA", "⚠️ بيانات ناقصة")]:
        names = "، ".join(html.escape(x["symbol"]) for x in states[state])
        if names:
            lines.append(f"{label} ({len(states[state])}): {names}")
    lines += [
        "",
        ("<b>كيف تقرأ الرسالة:</b> إغلاق شمعتين متتاليتين (5 دقائق) فوق النطاق المرجعي = مراقبة صعود، "
         "وتحته = مراقبة هبوط. الأهداف امتدادات فيبوناتشي للنطاق نفسه."),
        ("⚠️ الأسعار متأخرة 16 دقيقة على الأقل وليست أسعار تنفيذ، والإشارة للسهم لا تثبت توفر عقد خيار مناسب. "
         "لا توجد نسبة نجاح مثبتة؛ راجع السعر الحي وسيولة العقد قبل أي قرار."),
    ]
    def size() -> int:
        return len("\n".join(lines)) + len(lines)  # at most one direction mark per line

    while size() > 3900 and len(lines) > 8:
        # Shorten the longest status list first; never cut inside a tag or a number.
        idx = max(range(len(lines) - 3), key=lambda i: len(lines[i]))
        head, sep, body = lines[idx].partition("): ")
        names = body.split("، ") if sep else []
        if len(names) > 8:
            lines[idx] = f"{head}{sep}{'، '.join(names[:8])} … و{len(names) - 8} أخرى"
            continue
        lines.pop(idx)
    return ar.render(lines)
