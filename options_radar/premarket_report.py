"""Owner-private pre-open report: session-relative slots and Arabic Telegram messages.

Slots follow the XNYS session of the day (New York time, DST and holidays from the
calendar, never fixed Riyadh offsets):
  EARLY  due 08:30 New York, window until 09:00
  FINAL  due 09:00 New York, window until the 09:30 open
A run outside both windows sends nothing. A send later than LATE_AFTER past the due time
is labelled late in the message and in the delivery marker; a slot whose window passed
with no run is recorded as MISSED, never sent afterwards.

Messages are built only from options_radar.premarket_map maps (computed once). Order:
1. summary: date, slot, data time, coverage, SPX/NDX status, index funds, every leader as
   one row (symbol, reference, frames, state, next levels) or its unavailable reason;
2. detailed cards: index funds first, then up to five WATCH names (none are forced).
Each message stays under Telegram's limit and is split only between rows.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from options_radar.analysis_card import scope_ar
from options_radar.telegram_ar import LRM, check_html, date_ar, rtl_line, when_ar

NY = ZoneInfo("America/New_York")
SLOTS = (("EARLY", (8, 30), (9, 0)), ("FINAL", (9, 0), (9, 30)))
LATE_AFTER = timedelta(minutes=10)
MAX_CHARS = 3900
SLOT_AR = {"EARLY": "التقرير المبكر قبل الافتتاح", "FINAL": "التقرير النهائي قبل الافتتاح"}
TREND_ARROW = {"UP": "↑", "DOWN": "↓", "MIXED": "↔"}
FRAME_SHORT = (("daily", "يومي"), ("1h", "ساعة"), ("15m", "15د"))
POSITION_AR = {"ABOVE_CALL_TRIGGER": "فوق محفز CALL قبل الافتتاح — يلزم تأكيد بعد الافتتاح",
               "BELOW_PUT_TRIGGER": "تحت محفز PUT قبل الافتتاح — يلزم تأكيد بعد الافتتاح",
               "INSIDE_WAIT_BAND": "داخل نطاق الانتظار"}
INDEX_BLOCKED_AR = ("SPX / NDX: غير متاح — لا مصدر مرخص لقيم المؤشر النقدي في هذا المسار؛ "
                    "SPY وQQQ صناديق مستقلة وليست بديلًا عن المؤشر.")


def _at(day: datetime, hm: tuple[int, int]) -> datetime:
    return day.astimezone(NY).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def slot_for(now: datetime, session_today: bool) -> dict[str, Any] | None:
    """The slot whose window contains `now` (New York time) on a session day, else None."""
    if not session_today:
        return None
    for name, due, until in SLOTS:
        due_at, end_at = _at(now, due), _at(now, until)
        if due_at <= now < end_at:
            return {"slot": name, "due_at": due_at.isoformat(), "window_end": end_at.isoformat(),
                    "late": now - due_at > LATE_AFTER, "late_minutes": int((now - due_at).total_seconds() // 60)}
    return None


def missed_slots(now: datetime, session_today: bool, done: set[str]) -> list[str]:
    """Slots whose window has fully passed today without a delivered report."""
    if not session_today:
        return []
    return [name for name, _, until in SLOTS if now >= _at(now, until) and name not in done]


def _p(value: Any) -> str:
    return f"{float(value):,.2f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"


def _sym(symbol: str) -> str:
    return f"<b>{html.escape(symbol)}</b>{LRM}"


def _frames(m: dict[str, Any]) -> str:
    frames = m.get("frames") or {}
    return " ".join(f"{label}{TREND_ARROW.get(frames.get(k), '؟')}" for k, label in FRAME_SHORT)


def row(m: dict[str, Any]) -> str:
    """One line per symbol; an unavailable symbol keeps its row with the reason."""
    if m.get("state") == "NO_DATA":
        return rtl_line(f"{_sym(m['symbol'])} — لا بيانات: {html.escape(str(m.get('reason') or 'غير معروف'))}")
    ref = m["reference"]
    gap = f" ({ref['gap_pct']:+.2f}%)" if isinstance(ref.get("gap_pct"), (int, float)) else ""
    return rtl_line(f"{_sym(m['symbol'])} {_p(ref['price'])}{gap} — {_frames(m)} — {m['state_ar']} — "
                    f"فوق {_p(m['call']['trigger'])} / تحت {_p(m['put']['trigger'])}")


def _targets(side: dict[str, Any]) -> str:
    parts = [f"{t['name']} {_p(t['value'])} ({t['method_ar']})" for t in side.get("targets") or []]
    return "، ".join(parts) if parts else "لا هدف مقاس بعد المحفز"


def card(m: dict[str, Any]) -> str:
    ref, pd, call, put = m["reference"], m["prior_day"], m["call"], m["put"]
    lines = [
        f"{_sym(m['symbol'])} — {m['state_ar']} — {POSITION_AR[m['position']]}",
        f"المرجع: {_p(ref['price'])} ({ref['type_ar']}، {html.escape(ref['time_ar'])})",
        (f"الجلسة السابقة {html.escape(str(pd['date']))}: قمة {_p(pd['high'])}، قاع {_p(pd['low'])}، "
        f"إغلاق {_p(pd['close'])}؛ المحور {_p(m['pivot'])}؛ ATR14 {_p(m['atr14'])}"),
        (f"CALL: محفز {_p(call['trigger'])}، تنبيه مبكر: إغلاق 5د فوقه بحجم ≥1.5× المعتاد، وتأكيد بإغلاق 30د؛ {_targets(call)}؛ "
        f"إبطال {_p(call['invalidation'])}"),
        (f"PUT: محفز {_p(put['trigger'])}، تنبيه مبكر: إغلاق 5د تحته بحجم ≥1.5× المعتاد، وتأكيد بإغلاق 30د؛ {_targets(put)}؛ "
        f"إبطال {_p(put['invalidation'])}"),
        (f"انتظار بين {_p(m['wait_band']['low'])} و{_p(m['wait_band']['high'])}؛ الأفق: الجلسة الحالية؛ "
        f"الأطر المتوافقة {m['aligned_frames']}/4."),
    ]
    sr = m.get("levels_sr") or {}
    parts = [f"{word} {_p(sr[key]['value'])} ({sr[key]['basis_ar']})"
             for key, word in (("resistance", "مقاومة"), ("support", "دعم")) if sr.get(key)]
    if parts:
        lines.append("، ".join(parts))
    return "\n".join(rtl_line(x) for x in lines)


def _pack(blocks: list[str], header: str) -> list[str]:
    """Greedy packing of whole blocks; a continuation message repeats a short header."""
    messages, current = [], header
    for block in blocks:
        candidate = f"{current}\n{block}"
        if len(candidate) > MAX_CHARS and current != header:
            messages.append(current)
            candidate = f"{header} (تابع)\n{block}"
        current = candidate
    messages.append(current)
    for text in messages:
        if len(text) > 4096:
            raise ValueError("a single block exceeds Telegram's limit")
        check_html(text)
    return messages


def render(maps: dict[str, dict[str, Any]], *, slot: dict[str, Any], now: datetime, session_date: str,
           index_funds: tuple[str, ...], detail_symbols: list[str], fetched: int, attempted: int,
           changed_since_early: int | None = None) -> list[str]:
    late = f" — متأخر {slot['late_minutes']} دقيقة عن موعده" if slot.get("late") else ""
    as_of = sorted({str(m.get("data_as_of")) for m in maps.values() if m.get("data_as_of")})
    scopes = sorted({scope_ar(m.get("feed_scope")) for m in maps.values() if m.get("feed_scope")})
    head = [
        f"<b>{SLOT_AR[slot['slot']]} — {date_ar(session_date)}</b>{late}",
        (f"أُعدّ {when_ar(now)}. شموع مكتملة حتى جلسة {html.escape(', '.join(as_of) or 'غير متاح')}؛ "
        f"لا شيء أحدث من 16 دقيقة."),
        (f"المصدر: Alpaca ({html.escape('; '.join(scopes) or 'غير مسمى')})؛ استخدام شخصي فقط. "
        f"التغطية: {fetched}/{attempted} رمزًا."),
        "WATCH مراقبة مشروطة لا توصية؛ لا احتمال نجاح ولا أمر تنفيذ. CONFIRMED لا يُعلن قبل الافتتاح.",
        "الخرائط المرسلة: صناديق المؤشرات وأفضل 3 شركات؛ اطلب أي خريطة أخرى بالأمر /map ثم الرمز.",
        INDEX_BLOCKED_AR,
    ]
    header = "\n".join(rtl_line(x) for x in head)
    rows = [rtl_line("<b>صناديق المؤشرات</b>")] + [row(maps[s]) for s in index_funds if s in maps]
    rows += leadership(maps)
    rows += [rtl_line("<b>الأسهم القيادية</b>")] + [row(m) for s, m in maps.items() if s not in index_funds]
    summary = _pack(rows, header)
    cards = [card(maps[s]) for s in detail_symbols if (maps.get(s) or {}).get("state") not in (None, "NO_DATA")]
    watches = [s for s, m in maps.items() if m.get("state") in ("CALL_WATCH", "PUT_WATCH")]
    if changed_since_early is not None:
        note = (f"بطاقات الرموز التي تغيّرت منذ التقرير المبكر فقط: {changed_since_early}."
                if changed_since_early else "لا تغيير جوهري في الحالات والمستويات منذ التقرير المبكر.")
    else:
        note = (f"الرموز بتوافق كامل للأطر الأربعة: {len(watches)}؛ البقية انتظار ولا فرص مفروضة."
                if watches else "لا رموز بتوافق كامل للأطر الأربعة اليوم؛ لا فرص مفروضة.")
    detail_header = rtl_line(f"<b>البطاقات التفصيلية — {date_ar(session_date)}</b>") + "\n" + rtl_line(note)
    details = _pack(cards, detail_header) if cards else []
    if changed_since_early == 0:
        details = [detail_header]
    return summary + details


def chart_caption(m: dict[str, Any]) -> str:
    """Short caption under a chart (Telegram limit 1024): state, reference, the two scenarios."""
    call, put = m["call"], m["put"]

    def first(side: dict[str, Any]) -> str:
        t = (side.get("targets") or [{}])[0]
        return f"{t['name']} {_p(t['value'])}" if t.get("value") else "لا هدف مقاس"

    lines = [f"{_sym(m['symbol'])} — {m['state_ar']} — المرجع {_p(m['reference']['price'])}",
             f"سيناريو CALL: إغلاق 5د بحجم مرتفع فوق {_p(call['trigger'])} ← {first(call)}؛ إبطال {_p(call['invalidation'])}",
             f"سيناريو PUT: إغلاق 5د بحجم مرتفع تحت {_p(put['trigger'])} ← {first(put)}؛ إبطال {_p(put['invalidation'])}",
             "مسار افتراضي مشروط، ليس توصية."]
    text = "\n".join(rtl_line(x) for x in lines)
    check_html(text)
    return text[:1024]


def leadership(maps: dict[str, dict[str, Any]], benchmark: str = "QQQ", n: int = 3) -> list[str]:
    """Who led and who lagged in the prior session relative to the benchmark fund (relative strength,
    from our own bars). Not an index-weight contribution: no authorized weight source is wired yet."""
    bench = (maps.get(benchmark) or {}).get("prior_change_pct")
    rows = [(s, m["prior_change_pct"]) for s, m in maps.items()
            if m.get("prior_change_pct") is not None and s not in ("SPY", "QQQ", "IWM", "DIA")]
    if bench is None or not rows:
        return []
    rows.sort(key=lambda x: -x[1])
    lead = "، ".join(f"{s} {c:+.2f}%" for s, c in rows[:n])
    lag = "، ".join(f"{s} {c:+.2f}%" for s, c in rows[-n:][::-1])
    against = [s for s, c in rows if (c > 0) != (bench > 0) and abs(c) >= 0.5]
    lines = [f"<b>القيادة في الجلسة السابقة</b> (مقارنة بـ {benchmark} {bench:+.2f}%؛ قوة نسبية لا أوزان مؤشر):",
             f"الأقوى: {lead}", f"الأضعف: {lag}"]
    if against:
        lines.append("عكس اتجاه السوق: " + "، ".join(against[:6]))
    return [rtl_line(html.escape(x) if "<b>" not in x else x) for x in lines]
