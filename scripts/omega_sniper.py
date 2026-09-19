from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from typing import Any

from scripts.sniper_signal import SniperEvent

GEX_URL = os.getenv("GHAZI_GEX_JSON_URL", "").strip()
TIMEOUT_SECONDS = 8


def _num(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _safe(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load_local_gex(symbol: str) -> dict[str, Any] | None:
    """Prefer the repository's validated gamma map over an arbitrary remote feed."""
    path = Path(os.getenv("GHAZI_GEX_STATE_PATH", "public/data/options_latest.json"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return None
    generated = str(payload.get("generated_at") or payload.get("timestamp") or "").strip()
    if generated:
        try:
            stamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds() / 60.0
            max_age = float(os.getenv("GHAZI_GEX_MAX_AGE_MINUTES", "45"))
            if age_minutes > max_age or age_minutes < -5:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    maps = payload.get("gamma_maps")
    if not isinstance(maps, dict):
        return None
    item = maps.get(symbol) or maps.get(symbol.upper()) or maps.get(symbol.lower())
    return item if isinstance(item, dict) else None


def _fetch_gex(symbol: str) -> dict[str, Any] | None:
    local = _load_local_gex(symbol)
    if local:
        return local
    if not GEX_URL:
        return None
    try:
        req = Request(GEX_URL, headers={"User-Agent": "GHAZIBOT-Omega/1.0"})
        with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _sessions_for_target(distance_pct: float, horizon: str, target: int) -> str:
    if horizon == "يومي":
        if distance_pct <= (0.004 if target == 1 else 0.008):
            return "نفس الجلسة غالبًا إذا استمر الزخم"
        if distance_pct <= (0.009 if target == 1 else 0.015):
            return "نفس الجلسة إلى جلستين"
        return "نحو 2–3 جلسات"
    if horizon == "أسبوعي":
        if distance_pct <= 0.01:
            return "1–3 جلسات"
        if distance_pct <= 0.02:
            return "2–5 جلسات"
        return "حتى 5–10 جلسات"
    if horizon == "شهري":
        if distance_pct <= 0.02:
            return "3–7 جلسات"
        if distance_pct <= 0.05:
            return "1–3 أسابيع"
        return "2–4 أسابيع"
    return "بحسب الفريم والزخم؛ لا يوجد تقدير زمني كافٍ"


def _gex_assessment(event: SniperEvent, gex: dict[str, Any] | None) -> dict[str, Any]:
    if event.symbol not in {"SPX", "SPXW", "$SPX", "SPX.X"} or not gex:
        return {"available": False}

    spot = _num(gex.get("spot")) or event.entry
    flip = _num(gex.get("zero_gamma_flip"))
    call_wall = _num(gex.get("call_wall"))
    put_wall = _num(gex.get("put_wall"))
    vol_trigger = _num(gex.get("vol_trigger"))
    regime = str(gex.get("gamma_regime") or "unknown").lower()

    if spot is None:
        return {"available": False}

    if flip is None:
        alignment = "محايد"
        shadow = 0
    else:
        gap = abs(spot - flip) / spot
        if gap <= 0.0015:
            alignment = "محايد — السعر قريب جدًا من غاما فليب"
            shadow = 0
        elif event.direction == "CALL":
            alignment = "داعم" if spot > flip else "معاكس"
            shadow = 10 if spot > flip else -10
        else:
            alignment = "داعم" if spot < flip else "معاكس"
            shadow = 10 if spot < flip else -10

    wall = call_wall if event.direction == "CALL" else put_wall
    target_warning = None
    if event.target_1 is not None and wall is not None:
        if event.direction == "CALL" and event.target_1 > wall:
            target_warning = "الهدف الأول يتجاوز جدار الكول؛ نتوقع مقاومة قبل/عند الجدار."
        elif event.direction == "PUT" and event.target_1 < wall:
            target_warning = "الهدف الأول يتجاوز جدار البوت؛ نتوقع دعمًا قبل/عند الجدار."

    if target_warning:
        shadow -= 5

    return {
        "available": True,
        "date": str(gex.get("date") or ""),
        "spot": spot,
        "flip": flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "vol_trigger": vol_trigger,
        "regime": regime,
        "alignment": alignment,
        "shadow_score": max(-15, min(15, shadow)),
        "target_warning": target_warning,
    }


def _fmt(value: float | None) -> str:
    if value is None:
        return "غير متوفر"
    return f"{value:,.2f}"


def format_omega_sniper_message(event: SniperEvent) -> str:
    spot = event.entry
    target1_pct = (
        abs(event.target_1 - spot) / spot
        if event.target_1 is not None and spot and spot != 0
        else None
    )
    target2_pct = (
        abs(event.target_2 - spot) / spot
        if event.target_2 is not None and spot and spot != 0
        else None
    )

    t1_window = (
        _sessions_for_target(target1_pct, event.horizon, 1)
        if target1_pct is not None else "لا يمكن تقديره قبل تحديد الدخول والهدف"
    )
    t2_window = (
        _sessions_for_target(target2_pct, event.horizon, 2)
        if target2_pct is not None else "لا يمكن تقديره قبل تحديد الدخول والهدف"
    )

    gex = _gex_assessment(event, _fetch_gex(event.symbol))
    lines = [
        f"{event.side_emoji} <b>أوميغا | {_safe(event.symbol)} | {event.side_ar}</b>",
        f"⭐ <b>درجة الإشارة: {event.score:.0f}/100</b> | الأفق: <b>{_safe(event.horizon)}</b> | الفريم: <b>{_safe(event.timeframe)}</b>",
        "",
        f"📍 <b>منطقة الدخول:</b> {_fmt(event.entry)}",
        f"⚡ <b>التفعيل:</b> {_fmt(event.trigger)}",
        f"🛑 <b>الإبطال:</b> {_fmt(event.stop)}",
        "",
        f"🎯 <b>الهدف الأول:</b> {_fmt(event.target_1)}",
        f"⏱️ نافذة الهدف الأول: <b>{_safe(t1_window)}</b>",
        f"🏁 <b>الهدف الثاني:</b> {_fmt(event.target_2)}",
        f"⏱️ نافذة الهدف الثاني: <b>{_safe(t2_window)}</b>",
    ]

    if gex.get("available"):
        regime_label = {
            "positive": "موجب",
            "negative": "سالب",
            "neutral": "محايد",
        }.get(gex["regime"], gex["regime"])
        lines += [
            "",
            "🧲 <b>طبقة غاما SPX</b>",
            f"النظام: <b>{_safe(regime_label)}</b> | التوافق مع الاتجاه: <b>{_safe(gex['alignment'])}</b>",
            f"غاما فليب: <b>{_fmt(gex['flip'])}</b> | جدار الكول: <b>{_fmt(gex['call_wall'])}</b> | جدار البوت: <b>{_fmt(gex['put_wall'])}</b>",
            f"محفز التقلب: <b>{_fmt(gex['vol_trigger'])}</b> | تاريخ البيانات: <b>{_safe(gex['date'])}</b>",
        ]
        if gex.get("target_warning"):
            lines.append(f"⚠️ <b>{_safe(gex['target_warning'])}</b>")
        lines.append(
            f"🧪 <b>توافق غاما الظلي: {gex['shadow_score']:+d}</b> — لا يغيّر درجة الإشارة حتى تتجمع عينة نتائج كافية."
        )
    else:
        lines += [
            "",
            "🧲 <b>طبقة غاما SPX:</b> غير متاحة الآن؛ لم تُستخدم في القرار.",
        ]

    lines += [
        "",
        "🧠 <b>قاعدة التنفيذ الذكي:</b> لا مطاردة. الدخول يكون داخل المنطقة المحددة أو بعد التفعيل؛ إذا كُسر الإبطال تُلغى الفكرة.",
        "📊 <b>الزمن تقديري وليس وعدًا:</b> النافذة مبنية على بُعد الهدف والفريم والأفق، وتُعاد معايرتها من النتائج الفعلية.",
        "🔎 <i>الغرض من طبقة غاما هو زيادة جودة السياق، لا الادعاء بمعرفة دفتر صانع السوق الحقيقي.</i>",
    ]
    message = "\n".join(lines)
    return message if len(message) <= 4096 else message[:4080].rstrip() + "\n…"
