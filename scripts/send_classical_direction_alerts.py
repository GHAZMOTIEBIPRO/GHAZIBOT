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

import exchange_calendars as xcals
import pandas as pd

from options_radar.site_links import chart_link_html
from options_radar.telegram_transport import send_html_message


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
    send_html_message(text)


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
        f"درجة توافق الأطر: <b>{int(row.get('agreement_pct') or 0)}/100</b> (ليست نسبة نجاح)",
        f"الأفق: <b>{_safe(row.get('horizon') or '1-5 جلسات تداول')}</b>",
        f"آخر شمعة 15د مكتملة: <b>{_safe(row.get('intraday_bar_closed_at') or 'غير متاحة')}</b> (UTC)",
        f"مصدر الشموع: <b>{_safe((row.get('market_data_sources') or {}).get('intraday') or 'غير متاح')}</b> — قد تكون البيانات مؤخرة",
        f"مصدر التحقق من أهلية الخيارات: <b>{_safe(row.get('optionability_source') or 'غير متاح')}</b> (لا يثبت جودة أو سعر العقد)",
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
    targets = row.get("targets") if isinstance(row.get("targets"), dict) else {}
    try:
        entry, t1, t2 = (float(targets[k]) for k in ("entry", "t1", "t2"))
        rr = float(targets["t1_reward_to_risk"])
    except (KeyError, TypeError, ValueError):
        entry = None
    if entry is not None and all(math.isfinite(v) and v > 0 for v in (entry, t1, t2)) and math.isfinite(rr):
        lines.append(
            f"• دخول مشروط: <b>${entry:,.2f}</b> | T1: <b>${t1:,.2f}</b> | T2: <b>${t2:,.2f}</b>"
        )
        lines.append(f"• عائد/مخاطرة نظري حتى T1: <b>{rr:.2f}</b> (ليس احتمال وصول)")

    lines.extend(
        [
            "",
            "ℹ️ <b>وش يعني التنبيه؟</b>",
            f"البوت يرجّح <b>{decision}</b> من تحليل السهم نفسه فقط. لا يستخدم سعر العقد أو OI أو Greeks أو Flow.",
            "اختيار السترايك وتاريخ الانتهاء غير داخل هذا التنبيه لأن بيانات العقود غير معتمدة حاليًا.",
        ]
    )
    link = chart_link_html(symbol)
    if link:
        lines.extend(["", link])
    return "\n".join(lines)


def _consistent_signal(row: dict[str, Any]) -> bool:
    """Reject contradictions between the signal, its own 15m bar and stop level."""
    try:
        price = float(row["price"])
        stop = float(row["invalidation_level"])
        intraday = row["intraday"]
        last_close = float(intraday["close"])
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in (price, stop, last_close)):
        return False
    if abs(price - last_close) > max(price, last_close) * 0.001:
        return False
    direction = str(row.get("decision") or "").upper()
    expected = "BULLISH" if direction == "CALL" else "BEARISH"
    if direction not in {"CALL", "PUT"}:
        return False
    if any(str((row.get(frame) or {}).get("direction") or "").upper() != expected for frame in ("daily", "hourly", "intraday")):
        return False
    return price > stop if direction == "CALL" else price < stop



def _fresh_session_bar(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Only send on a live NYSE session using a completed, recently observed 15m bar.

    The timestamp comes from the provider bar index; never from generated_at.
    Outside regular sessions, including manual dispatch, no alert is sent.
    """
    raw = row.get("intraday_bar_closed_at")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        closed = pd.Timestamp(raw)
        reference = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
        if closed.tzinfo is None or reference.tzinfo is None:
            return False
        closed = closed.tz_convert("UTC")
        reference = reference.tz_convert("UTC")
        calendar = xcals.get_calendar("XNYS")
        minute = reference.floor("min")
        if not calendar.is_open_on_minute(minute):
            return False
        session = calendar.minute_to_session(minute, direction="none")
        if closed < calendar.session_open(session) + pd.Timedelta(minutes=15):
            return False
        return bool(closed <= reference and reference - closed <= pd.Timedelta(minutes=45))
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    if payload.get("path") != "classical_direction":
        raise RuntimeError("Expected classical_direction payload")
    maximum = max(1, min(5, int(os.getenv("CLASSICAL_ALERT_MAX", "3"))))
    candidates = [row for row in payload.get("signals", []) if isinstance(row, dict) and row.get("decision") in {"CALL", "PUT"}
                  # NO_TRADE: direction stands but T1 reward/risk < 1; never alerted.
                  and row.get("trade_status") in (None, "ACTIONABLE")]
    signals = [row for row in candidates if _consistent_signal(row) and _fresh_session_bar(row)]
    state["blocked_invalid_or_stale"] = len(candidates) - len(signals)
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
    parser = argparse.ArgumentParser(
        description="Send Arabic underlying-only classical CALL/PUT alerts"
    )
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
