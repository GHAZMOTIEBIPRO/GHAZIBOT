"""Send bounded, deduplicated BLS event reminders using the EXISTING news state.

Never issues CALL/PUT, forecasts the economic result or extrapolates market
direction. Does not overwrite the company-news sender's own sent-state.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.telegram_transport import send_html_message


def select_macro_reminders(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    advance_minutes: int = 90,
    maximum: int = 2,
) -> list[dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    try:
        generated = datetime.fromisoformat(str(context.get("generated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return []
    if generated.tzinfo is None or not timedelta(0) <= current - generated <= timedelta(minutes=40):
        return []
    records = context.get("bls_upcoming")
    if not isinstance(records, list):
        return []
    previous = state.get("macro_sent") if isinstance(state.get("macro_sent"), dict) else {}
    result = []
    for row in records:
        if not isinstance(row, dict) or row.get("authority") != "OFFICIAL_SCHEDULE":
            continue
        if row.get("source") != "bls_official_ical" or row.get("economic_result_available") is not False:
            continue
        try:
            at = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None or not timedelta(0) < at - current <= timedelta(minutes=advance_minutes):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        key = hashlib.sha256(f"{title}|{at.isoformat()}".encode()).hexdigest()[:24]
        if key in previous:
            continue
        result.append({**row, "key": key, "minutes_to_release": int((at - current).total_seconds() / 60)})
    return sorted(result, key=lambda x: x["scheduled_at"])[:max(0, min(4, maximum))]


def format_macro_message(row: dict[str, Any]) -> str:
    title = html.escape(str(row.get("title") or "")[:180])
    when = html.escape(str(row.get("scheduled_at") or "")[:40])
    left = int(row.get("minutes_to_release") or 0)
    return (
        "📆 <b>BLACK BOX | تنبيه حدث اقتصادي أمريكي</b>\n"
        f"الإصدار: <b>{title}</b>\n"
        f"موعد النشر الرسمي: <b>{when}</b> (UTC)\n"
        f"متبقٍ نحو <b>{left} دقيقة</b>.\n"
        "قد يرتفع التذبذب وقت الإعلان. لا نعرف نتيجة البيان مسبقًا؛ "
        "هذه ليست إشارة CALL أو PUT ولا إثباتًا لاتجاه السوق.\n"
        '<a href="https://www.bls.gov/schedule/news_release/bls.ics">جدول BLS الرسمي</a>'
    )


def send_from_file(
    context_path: Path, state_path: Path, *,
    now: datetime | None = None, send=send_html_message,
) -> dict[str, Any]:
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "NO_FRESH_CONTEXT", "sent": 0}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, json.JSONDecodeError):
        state = {}
    current = now or datetime.now(timezone.utc)
    candidates = select_macro_reminders(context, state, now=current)
    registry = state.setdefault("macro_sent", {})
    if not isinstance(registry, dict):
        registry = {}
        state["macro_sent"] = registry
    sent = 0
    for event in candidates:
        # State is only marked AFTER Telegram confirms delivery.
        receipt = send(format_macro_message(event))
        registry[event["key"]] = {
            "sent_at": current.isoformat(),
            "scheduled_at": event["scheduled_at"],
            "message_id": getattr(receipt, "message_id", None),
        }
        sent += 1
    cutoff = current - timedelta(days=3)
    for key, row in list(registry.items()):
        try:
            at = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            at = None
        if at is None or at.tzinfo is None or at < cutoff:
            registry.pop(key, None)
    if sent:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(state_path)
    return {"status": "READY", "sent": sent, "fresh_context": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded BLS economic reminders, using existing news state")
    parser.add_argument("--context", default="public/data/free_public_intelligence.json")
    parser.add_argument("--state", default="data/live/company_news_alert_state.json")
    args = parser.parse_args()
    result = send_from_file(Path(args.context), Path(args.state))
    print(f"Macro reminder: status={result['status']} sent={result['sent']}")


if __name__ == "__main__":
    main()
