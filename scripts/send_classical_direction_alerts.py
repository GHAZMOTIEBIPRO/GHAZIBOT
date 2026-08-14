from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def _safe(value: Any) -> str:
    return html.escape(str(value or "").strip())


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
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected classical-direction message")


def _fingerprint(row: dict[str, Any]) -> str:
    raw = "|".join(
        str(value or "")
        for value in (
            row.get("symbol"),
            row.get("decision"),
            row.get("priority"),
            round(float(row.get("confirmation_level") or 0), 2),
            round(float(row.get("invalidation_level") or 0), 2),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _frame_ar(view: dict[str, Any]) -> str:
    direction = str(view.get("direction") or "NEUTRAL")
    return {
        "BULLISH": "صاعد ✅",
        "BEARISH": "هابط 🔻",
        "NEUTRAL": "محايد ⚪",
    }.get(direction, "محايد ⚪")


def _priority_ar(value: Any) -> str:
    return "عالية جدًا" if str(value).upper() == "HIGH" else "متوسطة"


def _message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    decision = str(row.get("decision") or "WAIT").upper()
    direction = "صعود" if decision == "CALL" else "هبوط"
    icon = "🟢" if decision == "CALL" else "🔴"
    price = float(row.get("price") or 0)
    confirmation = row.get("confirmation_level")
    invalidation = row.get("invalidation_level")
    daily = row.get("daily") if isinstance(row.get("daily"), dict) else {}
    hourly = row.get("hourly") if isinstance(row.get("hourly"), dict) else {}
    intraday = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    reasons = [str(item) for item in row.get("reasons_ar", []) if str(item).strip()]

    lines = [
        f"{icon} <b>بلاك بوكس Ω | اتجاه كلاسيكي</b>",
        "",
        f"السهم: <b>{_safe(symbol)}</b> | السعر: <b>${price:,.2f}</b>",
        f"القرار: <b>{decision} — {direction}</b>",
        f"قوة المتابعة: <b>{_priority_ar(row.get('priority'))}</b>",
        f"الأفق: <b>{_safe(row.get('horizon') or '1-5 جلسات تداول')}</b>",
        "",
        "📐 <b>اتفاق الاتجاه</b>",
        f"اليومي: <b>{_frame_ar(daily)}</b> | الساعة: <b>{_frame_ar(hourly)}</b> | 15د: <b>{_frame_ar(intraday)}</b>",
    ]

    if reasons:
        lines.extend(["", "🧭 <b>أقوى الأسباب الكلاسيكية</b>"])
        lines.extend(f"• {_safe(reason)}" for reason in reasons[:4])

    lines.extend(["", "🎯 <b>متى أتأكد ومتى ألغي الفكرة؟</b>"])
    if confirmation:
        word = "فوق" if decision == "CALL" else "تحت"
        lines.append(f"• تأكيد أقوى إذا ثبت السهم {word} <b>${float(confirmation):,.2f}</b>")
    else:
        lines.append("• لا يوجد مستوى تأكيد واضح الآن؛ لا تطارد الحركة.")
    if invalidation:
        word = "تحت" if decision == "CALL" else "فوق"
        lines.append(f"• تضعف/تلغى الفكرة إذا عاد السهم {word} <b>${float(invalidation):,.2f}</b>")

    lines.extend(
        [
            "",
            "ℹ️ <b>وش يعني التنبيه؟</b>",
            f"البوت يرجّح <b>{decision}</b> من تحليل السهم نفسه فقط. لا يستخدم سعر العقد أو OI أو Greeks أو Flow.",
            "اختيار السترايك وتاريخ الانتهاء غير داخل هذا التنبيه لأن بيانات العقود غير معتمدة حاليًا.",
        ]
    )
    return "\n".join(lines)


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    if payload.get("path") != "classical_direction":
        raise RuntimeError("Expected classical_direction payload")
    maximum = max(1, min(5, int(os.getenv("CLASSICAL_ALERT_MAX", "3"))))
    signals = [
        row
        for row in payload.get("signals", [])
        if isinstance(row, dict) and row.get("decision") in {"CALL", "PUT"}
    ]
    signals.sort(
        key=lambda row: (
            1 if row.get("priority") == "HIGH" else 0,
            float(row.get("rank_score") or 0),
        ),
        reverse=True,
    )
    sent_map = state.setdefault("sent", {})
    sent = 0
    for row in signals:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper()
        fp = _fingerprint(row)
        if sent_map.get(symbol) == fp:
            continue
        _send(_message(row))
        sent_map[symbol] = fp
        sent += 1
    state["path"] = "classical_direction"
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_sent_count"] = sent
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Arabic underlying-only classical CALL/PUT alerts")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    sent = send(payload, state)
    _save(args.state, state)
    print(f"Classical direction Telegram sender: sent={sent}")


if __name__ == "__main__":
    main()
