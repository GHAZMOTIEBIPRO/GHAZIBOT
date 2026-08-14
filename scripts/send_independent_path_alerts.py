from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def _safe(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _send(text: str) -> None:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram destination is not ready")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram rejected message: {body}")


def _fingerprint(parts: list[Any]) -> str:
    raw = "|".join(str(value or "") for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _stage_ar(stage: str) -> str:
    return {
        "WATCH": "مراقبة",
        "PRESSURE_BUILDING": "بناء ضغط قبل الحركة",
        "IGNITION": "بداية انطلاقة",
        "EXPLOSION": "حركة قوية",
        "EXTENDED": "حركة ممتدة ومتأخرة",
    }.get(stage.upper(), stage or "غير مصنف")


def _side_ar(side: str) -> str:
    return "CALL — اتجاه صاعد" if side.upper() == "CALL" else "PUT — اتجاه هابط"


def _activity_ar(ratio: float) -> str:
    if ratio >= 3:
        return "نشاط مرتفع جدًا مقارنة بالعقود المفتوحة"
    if ratio >= 1:
        return "نشاط مرتفع مقارنة بالعقود المفتوحة"
    if ratio > 0:
        return "النشاط موجود لكنه أقل من العقود المفتوحة"
    return "لا توجد مقارنة موثوقة بين الحجم والعقود المفتوحة"


def _stock_message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    score = _number(row.get("score"))
    price = _number(row.get("price"))
    move = _number(row.get("move_pct"))
    stage = str(row.get("stage") or "WATCH").upper()
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    cause_status = str(cause.get("status_ar") or "السبب الأساسي غير مثبت حتى الآن")
    cause_headline = str(cause.get("headline") or "").strip()
    cause_source = str(cause.get("source") or "").strip()
    source_tier = str(cause.get("source_tier") or "").strip()
    amplifiers = [str(value) for value in row.get("amplifiers", []) if str(value).strip()]
    halts = [value for value in row.get("market_status_evidence", []) if isinstance(value, dict)]

    if move > 0:
        move_text = f"صاعد {move:+.1f}%"
    elif move < 0:
        move_text = f"هابط {move:+.1f}%"
    else:
        move_text = "بدون تغير واضح"

    lines = [
        "🚀 <b>بلاك بوكس Ω | تنبيه سهم</b>",
        "",
        f"<b>{_safe(symbol)}</b> | السعر <b>${price:,.2f}</b>",
        f"الحركة الآن: <b>{_safe(move_text)}</b>",
        f"مرحلة الحركة: <b>{_safe(_stage_ar(stage))}</b>",
        f"درجة الرادار: <b>{score:.0f}/100</b> <i>— درجة ترتيب وليست نسبة نجاح</i>",
        "",
        "🧭 <b>الخلاصة</b>",
        "السهم دخل قائمة المتابعة لأن سلوكه الحالي أقوى من المعتاد حسب شروط الرادار. التنبيه ليس أمر شراء؛ فائدته أن يلفت انتباهك مبكرًا لما يستحق الفحص.",
        "",
        "🧨 <b>لماذا ظهر؟</b>",
        f"• {_safe(cause_status)}",
    ]
    if cause_headline:
        lines.append(f"• {_safe(cause_headline, 500)}")
    if cause_source:
        tier_text = f" — {_safe(source_tier)}" if source_tier else ""
        lines.append(f"• المصدر: <b>{_safe(cause_source)}</b>{tier_text}")
    if amplifiers:
        lines.extend(["", "🔥 <b>ما الذي يدعم الحركة؟</b>"])
        lines.extend(f"• {_safe(item, 260)}" for item in amplifiers[:4])
    if halts:
        lines.extend(["", "⏸ <b>تنبيه حالة السوق</b>"])
        for event in halts[:2]:
            lines.append(f"• {_safe(event.get('reason'))}: {_safe(event.get('note_ar'), 360)}")

    lines.extend(["", "⚠️ <b>أهم مخاطرة في التنبيه</b>"])
    if "غير مثبت" in cause_status or "NO_PRIMARY" in str(cause.get("status") or ""):
        lines.append("• لا يوجد حتى الآن سبب رسمي مثبت للحركة؛ قد تكون الحركة مضاربية أو مؤقتة.")
    if stage == "EXTENDED":
        lines.append("• الحركة ممتدة أصلًا؛ خطر المطاردة أعلى من فرصة الدخول المبكر.")
    else:
        lines.append("• القوة الحالية قد تختفي سريعًا إذا ضعف الحجم أو انعكس السعر.")

    lines.extend(
        [
            "",
            "👀 <b>وش أسوي الآن؟</b>",
            "راقب استمرار الحركة والحجم والسبب قبل أي قرار. مسار الأسهم مستقل ولا يحتاج وجود أوبشن حتى يظهر السهم.",
        ]
    )
    return "\n".join(lines)


def _option_message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    side = str(row.get("option_type") or "").upper()
    expiration = str(row.get("expiration") or "")[:10]
    dte = int(_number(row.get("dte")))
    strike = _number(row.get("strike"))
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    ratio = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    delta = _number(row.get("delta"))
    gamma = _number(row.get("gamma"))
    theta = _number(row.get("theta"))
    iv = _number(row.get("iv"))
    spread = _number(row.get("spread_pct"))
    score = _number(row.get("score"))
    flow_score = _number(row.get("flow_momentum_score"))
    evidence = row.get("flow_evidence") if isinstance(row.get("flow_evidence"), dict) else {}
    reasons = [str(value) for value in row.get("rationale_ar", []) if str(value).strip()]
    readiness = row.get("_provider_readiness") if isinstance(row.get("_provider_readiness"), dict) else {}
    quote_ready = readiness.get("production_quote_ready") is True
    flow_ready = readiness.get("production_flow_ready") is True

    lines = [
        "🎯 <b>بلاك بوكس Ω | تنبيه عقد أوبشن</b>",
        "",
        f"الأصل: <b>{_safe(symbol)}</b>",
        f"الاتجاه المرصود: <b>{_safe(_side_ar(side))}</b>",
        f"العقد: <b>{_safe(symbol)} {side} {strike:g}</b>",
        f"الانتهاء: <b>{_safe(expiration)}</b> | المتبقي <b>{dte} يوم</b>",
        f"سعر العقد: <b>${bid:.2f} / ${ask:.2f}</b>" + (f" | المتوسط ≈ <b>${mid:.2f}</b>" if mid else ""),
        f"فرق العرض والطلب: <b>{spread * 100:.1f}%</b>",
        "",
        "🧭 <b>الخلاصة</b>",
        f"العقد اجتاز شروط الرادار بدرجة <b>{score:.0f}/100</b>، ودرجة نشاط التدفق <b>{flow_score:.0f}/100</b>. هذه درجات ترتيب وليست احتمال ربح.",
        "",
        "📊 <b>نشاط العقد ببساطة</b>",
        f"• حجم اليوم: <b>{volume:,}</b> عقد",
        f"• العقود المفتوحة OI: <b>{oi:,}</b>",
        f"• الحجم ÷ OI: <b>{ratio:.2f}×</b> — {_safe(_activity_ar(ratio))}",
        "",
        "🧪 <b>حساسية العقد</b>",
        f"• دلتا: <b>{delta:+.2f}</b> — حساسية سعر العقد لحركة الأصل",
        f"• ثيتا: <b>{theta:.4f}</b> — أثر مرور الوقت على قيمة العقد",
        f"• غاما: <b>{gamma:.4f}</b> — سرعة تغير الدلتا",
        f"• التذبذب الضمني IV: <b>{iv:.1%}</b>",
    ]

    if reasons:
        lines.extend(["", "🧠 <b>ليش اختاره الرادار؟</b>"])
        lines.extend(f"• {_safe(item, 390)}" for item in reasons[:4])

    pressure = str(evidence.get("execution_pressure_note_ar") or "").strip()
    oi_note = str(evidence.get("volume_vs_prior_oi_note_ar") or "").strip()
    if pressure or oi_note:
        lines.extend(["", "🔬 <b>قراءة التدفق</b>"])
        if pressure:
            lines.append(f"• {_safe(pressure, 430)}")
        if oi_note:
            lines.append(f"• {_safe(oi_note, 430)}")

    if readiness:
        lines.extend(["", "🛰 <b>جودة البيانات</b>"])
        lines.append(f"• أسعار إنتاجية: <b>{'نعم ✅' if quote_ready else 'لا ❌'}</b>")
        lines.append(f"• تدفق صفقات حي كامل: <b>{'نعم ✅' if flow_ready else 'غير مكتمل ⚠️'}</b>")

    lines.extend(
        [
            "",
            "⚠️ <b>ما الذي لا نعتبره مؤكدًا؟</b>",
            "• السويب غير مؤكد من لقطة سلسلة العقود وحدها.",
            "• فتح مركز جديد غير مؤكد حتى يؤكده تغير العقود المفتوحة بعد التسوية.",
            "• ارتفاع الحجم لا يثبت وحده أن المتداول اشترى العقد للمضاربة؛ قد يكون تحوطًا أو جزءًا من استراتيجية مركبة.",
            "",
            "👀 <b>وش أسوي الآن؟</b>",
            "استخدم التنبيه كأولوية للمراقبة: تأكد أن اتجاه الأصل نفسه يؤيد العقد، وأن السيولة والسبريد ما تدهورت قبل أي تنفيذ.",
            "<i>مسار الأوبشن مستقل ولا ينتظر إشارة من مسار الأسهم.</i>",
        ]
    )
    return "\n".join(lines)


def send_stocks(payload: dict[str, Any], state: dict[str, Any]) -> int:
    minimum = _number(os.getenv("STOCK_ALERT_MIN_SCORE", "72"), 72.0)
    maximum = max(1, min(5, int(_number(os.getenv("STOCK_ALERT_MAX", "3"), 3))))
    rows = [row for row in payload.get("stocks", []) if isinstance(row, dict)]
    rows.sort(key=lambda row: _number(row.get("score")), reverse=True)
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in rows:
        if sent >= maximum:
            break
        score = _number(row.get("score"))
        stage = str(row.get("stage") or "WATCH").upper()
        if score < minimum or stage == "WATCH":
            continue
        symbol = str(row.get("symbol") or "").upper()
        cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
        fp = _fingerprint([symbol, stage, round(score / 4) * 4, cause.get("status"), cause.get("headline")])
        if sent_map.get(symbol) == fp:
            continue
        _send(_stock_message(row))
        sent_map[symbol] = fp
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "stocks"
    return sent


def send_options(payload: dict[str, Any], state: dict[str, Any]) -> int:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is not True:
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        state["last_sent_count"] = 0
        state["path"] = "options"
        state["blocked_reason"] = str(readiness.get("status") or "PROVIDER_NOT_READY")
        return 0

    minimum = _number(os.getenv("OPTIONS_ALERT_MIN_SCORE", "65"), 65.0)
    maximum = max(1, min(6, int(_number(os.getenv("OPTIONS_ALERT_MAX", "4"), 4))))
    rows = [row for row in payload.get("contracts", []) if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            _number(row.get("flow_rank_score")),
            _number(row.get("flow_momentum_score")),
            _number(row.get("score")),
        ),
        reverse=True,
    )
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in rows:
        if sent >= maximum:
            break
        score = _number(row.get("score"))
        if score < minimum:
            continue
        contract = str(row.get("contract_symbol") or "").upper().strip()
        if not contract:
            contract = _fingerprint([row.get("symbol"), row.get("option_type"), row.get("expiration"), row.get("strike")])
        fp = _fingerprint(
            [
                contract,
                round(_number(row.get("flow_momentum_score")) / 5) * 5,
                round(_number(row.get("vol_to_oi_ratio") or row.get("vol_oi")), 1),
                round(_number(row.get("ask")), 2),
            ]
        )
        if sent_map.get(contract) == fp:
            continue
        message_row = dict(row)
        message_row["_provider_readiness"] = readiness
        _send(_option_message(message_row))
        sent_map[contract] = fp
        sent += 1
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    state["path"] = "options"
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send independent stock/options BLACK BOX alerts")
    parser.add_argument("--path", choices=("stocks", "options"), required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()

    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    if not isinstance(payload, dict) or not isinstance(state, dict):
        raise RuntimeError("Invalid payload/state")
    expected = "stocks" if args.path == "stocks" else "options"
    if payload.get("path") != expected:
        raise RuntimeError(f"Expected {expected} payload, got {payload.get('path')!r}")

    sent = send_stocks(payload, state) if args.path == "stocks" else send_options(payload, state)
    _save(args.state, state)
    print(f"Independent Telegram sender: path={args.path} sent={sent}")


if __name__ == "__main__":
    main()
