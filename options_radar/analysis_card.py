"""Analysis card: one symbol's reading built only from computed, tested fields.

The plan (options_radar.daily_plan) computes; this module assembles what a reader
needs and writes the Arabic text from a fixed template. Layers stay apart:
observed (bars, levels on named bars), interpretation (frame trend by a stated
rule, agreement as a count), scenario (conditional, with invalidation, no
probability). `numbers_supported` rejects any text, for example a language-model
rewrite, that contains a number the card does not hold.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "ghazi.analysis_card.v1"
ETFS = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "SMH", "TLT", "GLD"}
INDEXES = {"SPX", "NDX", "DJI", "RUT", "VIX"}
FRAME_AR = {"weekly": "الأسبوعي", "daily": "اليومي", "4h": "4 ساعات", "1h": "الساعة", "15m": "15 دقيقة", "5m": "5 دقائق"}
TREND_AR = {"UP": "صاعد", "DOWN": "هابط", "MIXED": "مختلط"}
# What each missing piece removes from the reading.
MISSING_IMPACT_AR = {
    "weekly": "لا اتجاه أسبوعي: القراءة لا تشمل الإطار الأكبر.",
    "daily": "لا خطة: المستويات تُقاس على آخر جلسة مكتملة.",
    "4h": "لا فريم 4 ساعات: لا تأكيد لاتجاه منتصف الأسبوع.",
    "1h": "لا فريم الساعة: لا يمكن تأكيد محفز الاختراق بشمعة ساعة مكتملة؛ المستويات اليومية تبقى صالحة.",
    "15m": "لا فريم 15 دقيقة: لا توقيت دقيق داخل الجلسة.",
    "5m": "لا فريم 5 دقائق: لا توقيت دقيق داخل الجلسة.",
    "atr14": "لا ATR14: لا مستوى إبطال محسوب للسيناريوهات.",
    "options": "قسم الخيارات غير متاح؛ لا يغيّر قراءة السهم.",
}
LEVEL_METHOD = {"prior_day_high": "قمة آخر جلسة مكتملة", "prior_day_low": "قاع آخر جلسة مكتملة",
                "prior_day_close": "إغلاق آخر جلسة مكتملة", "prior_week_high": "قمة آخر أسبوع مكتمل",
                "prior_week_low": "قاع آخر أسبوع مكتمل"}
LEVEL_AR = {"prior_day_high": "قمة آخر جلسة", "prior_day_low": "قاع آخر جلسة", "prior_day_close": "إغلاق آخر جلسة",
            "prior_week_high": "قمة الأسبوع السابق", "prior_week_low": "قاع الأسبوع السابق"}


def scope_ar(scope: Any) -> str:
    text = str(scope or "")
    if "IEX" in text.upper():
        return "تغذية IEX فقط، حجم جزئي"
    if "SIP" in text.upper() or "consolidated" in text.lower():
        return "الشريط المجمع SIP"
    return text or "مصدر غير مسمى"


def asset_type(symbol: str) -> str:
    return "INDEX" if symbol in INDEXES else "ETF" if symbol in ETFS else "STOCK"


def build_card(plan: dict[str, Any], *, news: list[dict[str, Any]] | None = None,
               options_status: str | None = None, quality: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = plan.get("symbol")
    if not plan.get("available"):
        return {"schema": SCHEMA, "symbol": symbol, "asset_type": asset_type(str(symbol)), "available": False,
                "reason": plan.get("reason"), "probability": None}
    frames = plan.get("frames") or {}
    missing = [{"item": k, "reason": f.get("reason"), "impact_ar": MISSING_IMPACT_AR[k]}
               for k, f in frames.items() if f.get("trend") in ("UNAVAILABLE", "INSUFFICIENT")]
    if plan.get("atr14") is None:
        missing.append({"item": "atr14", "reason": "fewer than 15 completed daily bars", "impact_ar": MISSING_IMPACT_AR["atr14"]})
    if options_status and options_status != "OK":
        missing.append({"item": "options", "reason": options_status, "impact_ar": MISSING_IMPACT_AR["options"]})
    linked = [{"date": n.get("date"), "title": n.get("title") or n.get("reason") or n.get("label"),
               "url": n.get("source_url") or n.get("url"), "source": n.get("source"), "kind": n.get("kind")}
              for n in (news or []) if (n.get("source_url") or n.get("url", "")).startswith("https://") and n.get("date")]
    q = quality or plan.get("quality_checks") or {}
    return {
        "schema": SCHEMA, "symbol": symbol, "asset_type": asset_type(str(symbol)), "available": True,
        "source": plan.get("provider"), "feed_scope": plan.get("provider_scope"),
        "data_as_of": plan.get("last_closed_session"), "delay_note": plan.get("delay_note"),
        "observed": {"prior_session": plan.get("prior_session"), "prior_week": plan.get("prior_week"),
                     "atr14": plan.get("atr14"),
                     "levels": [{**lv, "method": LEVEL_METHOD.get(lv["name"], lv["name"])} for lv in plan.get("levels") or []]},
        "interpretation": {"frames": {k: {"trend": f.get("trend"), "basis": f.get("basis"), "structure": f.get("structure"),
                                          "last_bar_end": f.get("last_bar_end")} for k, f in frames.items()},
                           "agreement": plan.get("agreement"), "liquidity": plan.get("liquidity_context")},
        "scenarios": plan.get("scenarios") or [],
        "news": linked[:5],
        "missing": missing,
        "data_quality": {k: {"status": v.get("status"), "issues": [i["code"] for i in v.get("issues") or []],
                             "completed": v.get("completed"), "forming": v.get("forming")} for k, v in q.items()},
        "probability": None, "execution_authority": False,
    }


def _fmt(v: Any) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def explain_ar(card: dict[str, Any]) -> str:
    """Deterministic Arabic reading from the card only."""
    if not card.get("available"):
        return f"{card.get('symbol')}: لا قراءة — {card.get('reason')}."
    frames = card["interpretation"]["frames"]
    voting = [(k, f["trend"]) for k, f in frames.items() if f["trend"] in TREND_AR]
    ups, downs = sum(1 for _, t in voting if t == "UP"), sum(1 for _, t in voting if t == "DOWN")
    lines = [f"{card['symbol']} ({scope_ar(card['feed_scope'])}، شموع مكتملة حتى جلسة {card['data_as_of']})"]
    lines.append("الفريمات: " + "، ".join(f"{FRAME_AR[k]} {TREND_AR[t]}" for k, t in voting)
                 + f" — {ups} صاعد و{downs} هابط من {len(voting)}؛ التوافق عدد فريمات وليس احتمالًا.")
    levels = card["observed"]["levels"]
    if levels:
        lines.append("المستويات: " + "، ".join(f"{LEVEL_AR.get(lv['name'], lv['name'])} {_fmt(lv['value'])} (شمعة {lv['bar']})"
                                                for lv in levels))
    for sc in card["scenarios"]:
        if sc.get("trigger_level") is None:
            continue
        side = "صعودي" if sc["kind"] == "BULLISH" else "هبوطي"
        target = (f"الهدف {_fmt(sc['target'])} ({'قمة الأسبوع السابق' if sc['kind'] == 'BULLISH' else 'قاع الأسبوع السابق'})"
                  if sc.get("target") is not None else "لا هدف مقاس")
        lines.append(f"سيناريو {side}: إن أغلقت شمعة ساعة مكتملة {'فوق' if sc['kind'] == 'BULLISH' else 'تحت'} "
                     f"{_fmt(sc['trigger_level'])}، {target}؛ يبطل عند {_fmt(sc['invalidation'])}.")
    for m in card["missing"]:
        lines.append("ناقص: " + m["impact_ar"])
    for n in card["news"]:
        lines.append(f"خبر رسمي ({n['date']}): {n['title']} — {n['url']}")
    lines.append("بلا احتمال نجاح ولا توصية تنفيذ.")
    return "\n".join(lines)


_NUM = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
# Fixed numbers of the method and the calendar: frame sizes, EMA/ATR lengths, the buffer, the delay.
METHOD_NUMBERS = {1.0, 4.0, 5.0, 15.0, 16.0, 20.0, 50.0, 14.0, 0.25, 10.0}


def _card_numbers(obj: Any, out: set[float]) -> set[float]:
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, str):
        for m in _NUM.findall(obj.translate(_ARABIC_DIGITS)):
            try:
                out.add(round(float(m.replace(",", "").replace("−", "-")), 2))
            except ValueError:
                continue
    elif isinstance(obj, dict):
        for v in obj.values():
            _card_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _card_numbers(v, out)
    return out


def numbers_supported(text: str, card: dict[str, Any]) -> tuple[bool, list[str]]:
    """Every number in `text` must be in the card (or a fixed method number)."""
    known = _card_numbers(card, set()) | METHOD_NUMBERS
    bad = []
    for m in _NUM.findall(text.translate(_ARABIC_DIGITS)):
        try:
            value = round(float(m.replace(",", "").replace("−", "-")), 2)
        except ValueError:
            continue
        if value not in known and abs(value) not in known:
            bad.append(m)
    return (not bad, bad)
