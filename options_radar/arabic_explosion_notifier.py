from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_TIMEOUT_SECONDS = 20
DEFAULT_PAYLOAD = Path("public/data/latest.json")
DEFAULT_FAST = Path("data/live/fast_explosion_scan.json")
DEFAULT_DELTA = Path("data/live/delta_signals.json")
DEFAULT_STATE = Path("data/live/arabic_explosion_alert_state.json")

STAGE_ORDER = {
    "WATCH": 0,
    "DORMANT": 0,
    "PRESSURE_BUILDING": 1,
    "PRE_EXPLOSION": 2,
    "IGNITION": 3,
    "EXPLOSION": 4,
    "EXTENDED": 5,
}

STAGE_AR = {
    "WATCH": "مراقبة",
    "DORMANT": "هادئ",
    "PRESSURE_BUILDING": "ضغط يتكوّن",
    "PRE_EXPLOSION": "قبل الانفجار",
    "IGNITION": "اشتعال مبكر",
    "EXPLOSION": "انفجار سعري",
    "EXTENDED": "ممتد / مطاردة",
}


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=API_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    for update in reversed(body.get("result") or []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return ""


def _send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        _telegram_url(token, "sendMessage"),
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("فشل إرسال رسالة تيليجرام")


def _stock_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in stocks
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _opportunity_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    rows = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _catalyst_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intel = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intel.get("by_symbol") if isinstance(intel.get("by_symbol"), dict) else {}
    return {str(symbol).upper(): row for symbol, row in by_symbol.items() if isinstance(row, dict)}


def _fast_map(fast: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = fast.get("actionable") if isinstance(fast.get("actionable"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _delta_map(delta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = delta.get("top_pressure") if isinstance(delta.get("top_pressure"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _halt_map(fast: dict[str, Any]) -> dict[str, dict[str, Any]]:
    halts = fast.get("halts") if isinstance(fast.get("halts"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in halts:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol:
            out[symbol] = row
    return out


def _rvol(stock: dict[str, Any]) -> float:
    return max(
        _num(stock.get("finviz_relative_volume")),
        _num(stock.get("relative_volume")),
        _num(stock.get("rvol")),
    )


def _float_shares(stock: dict[str, Any], delta: dict[str, Any]) -> float:
    for value in (
        delta.get("effective_float"),
        stock.get("effective_float_estimate"),
        stock.get("public_float_shares"),
        stock.get("float_shares"),
        stock.get("public_float"),
        stock.get("float"),
    ):
        number = _num(value)
        if number > 0:
            return number
    return 0.0


def _trigger(opportunity: dict[str, Any], stock: dict[str, Any]) -> float | None:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    entry = target_map.get("entry") if isinstance(target_map.get("entry"), dict) else {}
    for value in (
        entry.get("high"),
        stock.get("entry_high"),
        stock.get("trigger"),
        stock.get("resistance20"),
        stock.get("previous_day_high"),
    ):
        number = _num(value, float("nan"))
        if math.isfinite(number) and number > 0:
            return number
    return None


def _invalidation(opportunity: dict[str, Any], stock: dict[str, Any]) -> float | None:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    invalidation = target_map.get("invalidation") if isinstance(target_map.get("invalidation"), dict) else {}
    for value in (invalidation.get("price"), stock.get("invalidation"), stock.get("stop")):
        number = _num(value, float("nan"))
        if math.isfinite(number) and number > 0:
            return number
    return None


def _format_price(value: float | None) -> str:
    if value is None or not math.isfinite(value) or value <= 0:
        return "غير متوفر"
    return f"${value:,.2f}"


def _translate_reason(reason: str) -> str:
    text = str(reason or "").strip()
    replacements = (
        ("Fast Delta", "تسارع بين الفحوص"),
        ("Supply Vacuum", "نقص المعروض"),
        ("Supply vacuum", "نقص المعروض"),
        ("RVOL", "الحجم النسبي"),
        ("Price Lag", "الحجم سبق السعر"),
        ("Information Change", "معلومة جديدة"),
        ("Social acceleration", "تسارع الاهتمام"),
        ("Catalyst quality", "جودة المحفز"),
        ("Materiality", "أهمية الخبر"),
        ("Public float", "الأسهم الحرة"),
        ("effective float", "الأسهم الحرة الفعلية"),
        ("locked/non-float estimate", "تقدير الأسهم المقفلة/غير الحرة"),
        ("Price elasticity", "حساسية السعر للسيولة"),
        ("Reaction", "استجابة السعر"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text


@dataclass(order=True)
class Cause:
    priority: float
    category: str = field(compare=False)
    text: str = field(compare=False)


@dataclass
class UnifiedCandidate:
    symbol: str
    price: float
    score: float
    stage: str
    day_move: float
    rvol: float
    causes: list[Cause]
    risks: list[str]
    primary_source: str
    source_url: str
    trigger: float | None
    invalidation: float | None
    headline: str
    timing: str

    @property
    def primary_cause(self) -> str:
        return self.causes[0].text if self.causes else "تغير متزامن في السعر والسيولة يحتاج متابعة"


def _candidate_from_symbol(
    symbol: str,
    stock: dict[str, Any],
    opportunity: dict[str, Any],
    cluster: dict[str, Any],
    fast: dict[str, Any],
    delta: dict[str, Any],
    halt: dict[str, Any],
) -> UnifiedCandidate | None:
    direction = str(opportunity.get("direction") or "UPSIDE").upper()
    if opportunity and direction not in {"UPSIDE", "LONG", "CALL"}:
        return None
    if opportunity.get("no_trade_state"):
        return None

    reaction = str(cluster.get("reaction_state") or "").upper()
    dilution = _num(cluster.get("dilution_risk"))
    max_dilution = _num(os.getenv("OMEGA_ARABIC_MAX_DILUTION", "75"), 75.0)
    if reaction == "EXTENDED_CHASING_RISK" or dilution >= max_dilution:
        return None

    fast_score = _num(fast.get("score"))
    omega_score = _num(opportunity.get("explosion_rank"))
    delta_score = _num(delta.get("score"))
    quality = _num(cluster.get("catalyst_quality"))
    materiality = _num(cluster.get("materiality"))
    confidence = _num(cluster.get("confidence"))
    if 0 < confidence <= 1:
        confidence *= 100.0
    catalyst_score = quality * 0.48 + materiality * 0.34 + confidence * 0.18

    score = max(fast_score, omega_score, delta_score, catalyst_score)
    stage_candidates = [
        str(fast.get("stage") or "WATCH").upper(),
        str(delta.get("stage") or "DORMANT").upper(),
    ]
    if omega_score >= 86:
        stage_candidates.append("EXPLOSION")
    elif omega_score >= 78:
        stage_candidates.append("IGNITION")
    elif omega_score >= 68:
        stage_candidates.append("PRESSURE_BUILDING")
    stage = max(stage_candidates, key=lambda item: STAGE_ORDER.get(item, 0))

    day_move = _num(fast.get("move_pct"), _num(stock.get("performance_day")))
    rvol = _rvol(stock)
    max_chase = _num(os.getenv("OMEGA_ARABIC_MAX_CHASE_PCT", "35"), 35.0)
    if stage == "EXTENDED" or day_move > max_chase:
        return None

    dimensions = opportunity.get("dimensions") if isinstance(opportunity.get("dimensions"), dict) else {}
    supply = max(
        _num(fast.get("supply_score")),
        _num(delta.get("supply_vacuum_score")),
        _num(dimensions.get("supply_structure")),
    )
    participation = _num(dimensions.get("participation"))
    options_score = _num(dimensions.get("options_structure"))
    turnover = _num(fast.get("turnover_pct"))
    volume = _num(fast.get("volume"), _num(stock.get("volume")))
    float_shares = _float_shares(stock, delta)

    causes: list[Cause] = []
    headline = str(cluster.get("headline") or cluster.get("title") or fast.get("news_headline") or "").strip()
    source = str(cluster.get("primary_source") or fast.get("news_source") or "").strip()
    source_url = str(cluster.get("primary_url") or "").strip()

    if halt:
        reason = str(halt.get("reason") or "").strip()
        title = str(halt.get("title") or halt.get("description") or "").strip()
        causes.append(Cause(108.0, "halt", f"إيقاف/استئناف تداول مرصود ({reason})" + (f": {title}" if title else "")))

    bias = str(cluster.get("directional_bias") or "").lower()
    if headline and quality >= 65 and materiality >= 60 and bias in {"bullish", "mixed", ""}:
        causes.append(
            Cause(
                100.0 + min(15.0, catalyst_score / 10.0),
                "news",
                f"خبر جوهري حديث: {headline}",
            )
        )

    if supply >= 70:
        causes.append(Cause(94.0 + min(5.0, supply / 25.0), "supply", f"المعروض محدود؛ درجة ضغط العرض {supply:.0f}/100"))
    if 0 < float_shares <= 10_000_000:
        causes.append(Cause(98.0, "float", f"الأسهم الحرة منخفضة جدًا ≈ {float_shares / 1_000_000:.2f} مليون سهم"))
    elif 0 < float_shares <= 25_000_000:
        causes.append(Cause(88.0, "float", f"الأسهم الحرة منخفضة ≈ {float_shares / 1_000_000:.1f} مليون سهم"))

    if rvol >= 2.5:
        causes.append(Cause(96.0, "volume", f"الحجم النسبي مشتعل عند {rvol:.2f} ضعف المعتاد"))
    elif rvol >= 1.5:
        causes.append(Cause(86.0, "volume", f"الحجم النسبي يتسارع إلى {rvol:.2f} ضعف المعتاد"))
    if participation >= 70:
        causes.append(Cause(89.0, "participation", f"مشاركة السيولة/الطلب مرتفعة {participation:.0f}/100"))
    if turnover >= 1.0:
        causes.append(Cause(91.0, "turnover", f"دوران السيولة مقابل القيمة السوقية مرتفع {turnover:.2f}%"))
    if volume >= 5_000_000:
        causes.append(Cause(79.0, "volume", f"حجم التداول الحالي مرتفع ≈ {volume:,.0f} سهم"))

    if 2 <= day_move <= 8:
        causes.append(Cause(84.0, "price", f"السعر بدأ يعيد التسعير مبكرًا: {day_move:+.1f}% اليوم"))
    elif 8 < day_move <= 25:
        causes.append(Cause(82.0, "price", f"الحركة السعرية بدأت فعليًا: {day_move:+.1f}% اليوم"))

    if options_score >= 70:
        causes.append(Cause(68.0, "options", f"هيكل عقود الخيارات داعم {options_score:.0f}/100"))

    for raw_reason in list(delta.get("reasons") or []) + list(fast.get("reasons") or []):
        reason = _translate_reason(str(raw_reason))
        if not reason:
            continue
        priority = 93.0 if "تسارع بين الفحوص" in reason else 88.0 if "يتسارع" in reason else 72.0
        causes.append(Cause(priority, "delta", reason))

    unique_causes: list[Cause] = []
    seen_causes: set[str] = set()
    for cause in sorted(causes, reverse=True):
        normalized = cause.text.lower()[:120]
        if normalized in seen_causes:
            continue
        seen_causes.add(normalized)
        unique_causes.append(cause)
        if len(unique_causes) >= 6:
            break

    min_score = _num(os.getenv("OMEGA_ARABIC_MIN_SCORE", "72"), 72.0)
    strong_catalyst = quality >= 80 and materiality >= 75 and reaction not in {"FAILED_REACTION", "EXTENDED_CHASING_RISK"}
    strong_stage = STAGE_ORDER.get(stage, 0) >= STAGE_ORDER["IGNITION"]
    pressure_with_causes = stage == "PRESSURE_BUILDING" and score >= min_score and len(unique_causes) >= 2
    if not (score >= min_score and (strong_stage or pressure_with_causes)) and not strong_catalyst:
        return None

    risks: list[str] = []
    if dilution >= 45:
        risks.append(f"مخاطر زيادة المعروض/التخفيف مرتفعة نسبيًا {dilution:.0f}/100")
    if day_move > 25:
        risks.append("السعر تقدم كثيرًا؛ احتمال المطاردة أعلى")
    if day_move >= 8 and rvol < 1.25:
        risks.append("الحركة السعرية لا يدعمها حجم نسبي قوي حتى الآن")
    if not headline:
        risks.append("لا يوجد محفز خبري موثق مسيطر؛ الحركة قد تكون مدفوعة بالعرض والطلب فقط")
    avg_dollar = _num(stock.get("avg_dollar_volume"))
    if 0 < avg_dollar < 3_000_000:
        risks.append("السيولة التاريخية محدودة وقد يزيد الانزلاق والتذبذب")
    opportunity_risks = opportunity.get("risks") if isinstance(opportunity.get("risks"), list) else []
    for risk in opportunity_risks[:2]:
        text = _translate_reason(str(risk))
        if text and text not in risks:
            risks.append(text)

    if day_move <= 8:
        timing = "مبكر نسبيًا"
    elif day_move <= 20:
        timing = "الحركة بدأت — يحتاج تأكيد وعدم مطاردة"
    else:
        timing = "متقدم — الحذر من المطاردة"

    price = _num(fast.get("price"), _num(opportunity.get("price"), _num(stock.get("price"))))
    return UnifiedCandidate(
        symbol=symbol,
        price=price,
        score=max(0.0, min(100.0, score)),
        stage=stage,
        day_move=day_move,
        rvol=rvol,
        causes=unique_causes,
        risks=risks[:4],
        primary_source=source,
        source_url=source_url,
        trigger=_trigger(opportunity, stock),
        invalidation=_invalidation(opportunity, stock),
        headline=headline,
        timing=timing,
    )


def build_candidates(payload: dict[str, Any], fast_payload: dict[str, Any], delta_payload: dict[str, Any]) -> list[UnifiedCandidate]:
    stocks = _stock_map(payload)
    opportunities = _opportunity_map(payload)
    catalysts = _catalyst_map(payload)
    fast = _fast_map(fast_payload)
    delta = _delta_map(delta_payload)
    halts = _halt_map(fast_payload)

    symbols = set(stocks) & (set(opportunities) | set(catalysts) | set(fast) | set(delta))
    candidates: list[UnifiedCandidate] = []
    for symbol in symbols:
        candidate = _candidate_from_symbol(
            symbol,
            stocks.get(symbol, {}),
            opportunities.get(symbol, {}),
            catalysts.get(symbol, {}),
            fast.get(symbol, {}),
            delta.get(symbol, {}),
            halts.get(symbol, {}),
        )
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(
        key=lambda row: (
            STAGE_ORDER.get(row.stage, 0),
            row.score,
            row.causes[0].priority if row.causes else 0.0,
        ),
        reverse=True,
    )
    return candidates


def _source_line(candidate: UnifiedCandidate) -> str:
    if not candidate.primary_source:
        return ""
    source = _safe(candidate.primary_source, 140)
    if candidate.source_url.startswith(("https://", "http://")):
        return f'\n🔗 <b>المصدر:</b> <a href="{html.escape(candidate.source_url, quote=True)}">{source}</a>'
    return f"\n🔗 <b>المصدر:</b> {source}"


def _reading(candidate: UnifiedCandidate) -> str:
    categories = {cause.category for cause in candidate.causes[:4]}
    if "news" in categories and ("float" in categories or "supply" in categories) and ("volume" in categories or "turnover" in categories):
        return "اجتمع محفز جوهري مع معروض محدود ودخول سيولة؛ هذه من أقوى التركيبات التي تسبق إعادة تسعير حادة، بشرط استمرار الحجم."
    if ("float" in categories or "supply" in categories) and ("volume" in categories or "turnover" in categories):
        return "المحرك الأساسي هيكلي: كمية الأسهم المتاحة محدودة والسيولة تضغط عليها بسرعة؛ أي استمرار في الطلب قد يوسّع الحركة."
    if "news" in categories:
        return "المحرك الأساسي خبر/معلومة جديدة؛ المطلوب الآن أن يثبت السعر والحجم أن السوق يعيد التسعير فعلًا."
    if "delta" in categories and ("volume" in categories or "participation" in categories):
        return "الشيء المهم ليس الرقم الحالي فقط؛ سرعة تغير الحجم والطلب بين الفحوص ترتفع قبل أن يبتعد السعر كثيرًا."
    return "عدة طبقات تحركت في الوقت نفسه، لكن استمرار الحجم وعدم تمدد السعر هما الشرطان الأهم قبل رفع الثقة."


def _confirmation(candidate: UnifiedCandidate) -> str:
    if candidate.trigger is not None:
        return f"اختراق/ثبات فوق {_format_price(candidate.trigger)} مع بقاء الحجم قويًا وعدم هبوطه بسرعة."
    if candidate.stage == "EXPLOSION":
        return "استمرار أحجام التداول القوية مع احتفاظ السعر بمعظم مكاسبه وعدم ظهور رفض حاد."
    return "تحول الضغط إلى حركة سعرية واضحة مع استمرار زيادة الحجم والسيولة في الفحص التالي."


def format_candidate_message(candidate: UnifiedCandidate) -> str:
    emoji = "💥" if candidate.stage == "EXPLOSION" else "🔥" if candidate.stage == "IGNITION" else "🚨"
    cause_lines = "\n".join(
        f"{idx}) {_safe(cause.text, 400)}" for idx, cause in enumerate(candidate.causes[:5], start=1)
    )
    risks = "\n".join(f"• {_safe(risk, 350)}" for risk in candidate.risks) or "• لا يوجد خطر حرج ظاهر في البيانات الحالية، لكن الإشارة تبقى قابلة للفشل."
    source = _source_line(candidate)
    invalidation = _format_price(candidate.invalidation)
    trigger = _format_price(candidate.trigger)

    return (
        f"{emoji} <b>بلاك بوكس Ω — تنبيه انفجار سعري</b>\n\n"
        f"<b>{_safe(candidate.symbol)}</b> — {_format_price(candidate.price)}\n"
        f"الحالة: <b>{_safe(STAGE_AR.get(candidate.stage, candidate.stage))}</b>\n"
        f"قوة الإشارة: <b>{candidate.score:.0f}/100</b> <i>(ترتيب داخلي وليست نسبة نجاح)</i>\n"
        f"حركة اليوم: <b>{candidate.day_move:+.1f}%</b>"
        + (f" | الحجم النسبي: <b>{candidate.rvol:.2f}×</b>" if candidate.rvol > 0 else "")
        + "\n\n"
        f"🧨 <b>المسبب الأقوى</b>\n{_safe(candidate.primary_cause, 700)}{source}\n\n"
        f"🔬 <b>مسببات الانفجار المرصودة</b>\n{cause_lines}\n\n"
        f"🧠 <b>قراءة البلاك بوكس</b>\n{_safe(_reading(candidate), 650)}\n\n"
        f"✅ <b>ما يؤكد استمرار الحركة</b>\n{_safe(_confirmation(candidate), 500)}\n\n"
        f"⚠️ <b>ما قد يضعفها</b>\n{risks}\n\n"
        f"🎯 نقطة التفعيل/المراقبة: <b>{trigger}</b>\n"
        f"🛑 مستوى إبطال الفكرة إن توفر: <b>{invalidation}</b>\n"
        f"⏱ التوقيت: <b>{_safe(candidate.timing)}</b>\n\n"
        "هذه قراءة آلية لحركة السوق ومسبباتها، وليست ضمانًا للارتفاع أو توصية شراء."
    )


def _fingerprint(candidate: UnifiedCandidate) -> str:
    seed = "|".join(
        [
            candidate.symbol,
            candidate.stage,
            f"{round(candidate.score / 5) * 5:.0f}",
            f"{candidate.day_move:.1f}",
            f"{candidate.rvol:.1f}",
            candidate.headline[:140],
            candidate.primary_cause[:180],
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _should_send(candidate: UnifiedCandidate, sent: dict[str, Any]) -> bool:
    previous = sent.get(candidate.symbol) if isinstance(sent.get(candidate.symbol), dict) else {}
    if not previous:
        return True
    if str(previous.get("fingerprint") or "") != _fingerprint(candidate):
        previous_score = _num(previous.get("score"))
        previous_stage = str(previous.get("stage") or "WATCH")
        stage_up = STAGE_ORDER.get(candidate.stage, 0) > STAGE_ORDER.get(previous_stage, 0)
        materially_stronger = candidate.score >= previous_score + 7
        cause_changed = str(previous.get("primary_cause") or "") != candidate.primary_cause[:180]
        return stage_up or materially_stronger or cause_changed
    return False


def _near_misses(payload: dict[str, Any], fast_payload: dict[str, Any], delta_payload: dict[str, Any], limit: int = 3) -> list[tuple[str, float, str]]:
    rows: dict[str, tuple[float, str]] = {}
    for symbol, row in _fast_map(fast_payload).items():
        score = _num(row.get("score"))
        reasons = list(row.get("reasons") or [])
        reason = _translate_reason(str(reasons[0])) if reasons else "حركة سعر/سيولة قريبة من شروط التنبيه"
        rows[symbol] = max(rows.get(symbol, (0.0, "")), (score, reason), key=lambda item: item[0])
    for symbol, row in _delta_map(delta_payload).items():
        score = _num(row.get("score"))
        reasons = list(row.get("reasons") or [])
        reason = _translate_reason(str(reasons[0])) if reasons else "ضغط يتكوّن بين الفحوص"
        rows[symbol] = max(rows.get(symbol, (0.0, "")), (score, reason), key=lambda item: item[0])
    for symbol, row in _opportunity_map(payload).items():
        score = _num(row.get("explosion_rank"))
        why = row.get("why") if isinstance(row.get("why"), list) else []
        reason = _translate_reason(str(why[0])) if why else "أقرب فرصة في محرك Ω"
        rows[symbol] = max(rows.get(symbol, (0.0, "")), (score, reason), key=lambda item: item[0])
    ordered = sorted(((symbol, score, reason) for symbol, (score, reason) in rows.items()), key=lambda item: item[1], reverse=True)
    return ordered[:limit]


def _status_message(payload: dict[str, Any], fast_payload: dict[str, Any], delta_payload: dict[str, Any]) -> str:
    generated = fast_payload.get("generated_at") or payload.get("generated_at") or payload.get("as_of") or "غير متوفر"
    near = _near_misses(payload, fast_payload, delta_payload)
    lines = [
        "🛰 <b>بلاك بوكس Ω — تقرير التشغيل الآلي</b>",
        "",
        "✅ البوت يعمل تلقائيًا والربط مع تيليجرام سليم.",
        "🔎 الفحص مستمر لمسببات الانفجارات: الأخبار، نقص المعروض، الحجم والسيولة، تسارع السعر، وتغير الضغط بين الفحوص.",
        "🚫 لا توجد فرصة جديدة تجاوزت جميع شروط التنبيه في هذا الفحص.",
        f"🕒 آخر بيانات متاحة: <b>{_safe(generated, 100)}</b>",
    ]
    if near:
        lines.extend(["", "👀 <b>أقرب الحالات حاليًا:</b>"])
        for index, (symbol, score, reason) in enumerate(near, start=1):
            lines.append(f"{index}) <b>{_safe(symbol)}</b> — {score:.0f}/100 — {_safe(reason, 260)}")
        lines.extend(["", "هذه قائمة مراقبة فقط. إذا اكتملت مسببات الحركة يوصلك تنبيه مستقل تلقائيًا."])
    return "\n".join(lines)


def notify(
    payload_path: Path,
    fast_path: Path,
    delta_path: Path,
    state_path: Path,
    *,
    dry_run: bool = False,
    force_status: bool = False,
) -> int:
    payload = _load(payload_path, {})
    fast_payload = _load(fast_path, {})
    delta_payload = _load(delta_path, {})
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(fast_payload, dict):
        fast_payload = {}
    if not isinstance(delta_payload, dict):
        delta_payload = {}
    if not payload and not fast_payload:
        print("Arabic notifier: no market payload available")
        return 0

    candidates = build_candidates(payload, fast_payload, delta_payload)
    state = _load(state_path, {"sent": {}})
    if not isinstance(state, dict):
        state = {"sent": {}}
    sent_map = state.setdefault("sent", {})
    if not isinstance(sent_map, dict):
        sent_map = {}
        state["sent"] = sent_map

    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = _resolve_chat_id(token) if token else ""
    if not dry_run and (not token or not chat_id):
        print("Arabic notifier: Telegram token/chat id unavailable")
        return 0

    max_alerts = max(1, min(5, int(_num(os.getenv("OMEGA_ARABIC_MAX_ALERTS", "3"), 3.0))))
    sent_count = 0
    for candidate in candidates:
        if sent_count >= max_alerts:
            break
        if not _should_send(candidate, sent_map):
            continue
        message = format_candidate_message(candidate)
        if dry_run:
            print(message)
            print("\n" + "-" * 60 + "\n")
        else:
            _send(token, chat_id, message)
        sent_map[candidate.symbol] = {
            "fingerprint": _fingerprint(candidate),
            "stage": candidate.stage,
            "score": round(candidate.score, 1),
            "primary_cause": candidate.primary_cause[:180],
            "sent_at": _utc_now(),
        }
        sent_count += 1

    now = datetime.now(timezone.utc)
    interval_hours = max(1.0, _num(os.getenv("OMEGA_ARABIC_STATUS_INTERVAL_HOURS", "4"), 4.0))
    last_status = _parse_time(state.get("last_status_sent_at"))
    status_due = force_status or last_status is None or now - last_status >= timedelta(hours=interval_hours)
    if sent_count == 0 and status_due:
        status = _status_message(payload, fast_payload, delta_payload)
        if dry_run:
            print(status)
        else:
            _send(token, chat_id, status)
        state["last_status_sent_at"] = now.isoformat()

    state["last_run_at"] = now.isoformat()
    state["last_candidate_count"] = len(candidates)
    state["last_sent_count"] = sent_count
    state["architecture"] = "unified_arabic_cause_based_sender_v1"
    _save(state_path, state)
    print(f"Arabic notifier: candidates={len(candidates)} sent={sent_count} status_due={status_due}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="موحد تنبيهات BLACK BOX Ω العربي المبني على مسببات الانفجار")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--fast", default=str(DEFAULT_FAST))
    parser.add_argument("--delta", default=str(DEFAULT_DELTA))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-status", action="store_true")
    args = parser.parse_args()
    try:
        return notify(
            Path(args.payload),
            Path(args.fast),
            Path(args.delta),
            Path(args.state),
            dry_run=args.dry_run,
            force_status=args.force_status,
        )
    except requests.RequestException as exc:
        print(f"Arabic notifier Telegram network error: {exc}")
        return 2
    except Exception as exc:
        print(f"Arabic notifier error: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
