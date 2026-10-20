"""Telegram alerts for important official FDA events (openFDA, CC0).

Sends one message per HIGH-importance event in runtime/public/data/fda_events.json:
an original NDA/BLA approval (a new drug or biologic) or a Class I recall.

- Dedupe: every event id that was sent or seeded is kept in the state file,
  and the fda-events workflow is that file's only writer.
- No stale backlog: the first run (no state yet) records the current events
  without sending them, and an event whose FDA date is older than
  --max-age-days is never sent. openFDA lags FDA decisions by days, so the
  age is measured from the FDA date, not from when we saw it.
- A message states the event as a regulatory fact with the official link;
  it is not a trade signal and implies no price direction.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = "ghazi.fda_alert_state.v1"
OFFICIAL_HOSTS = {"www.accessdata.fda.gov", "accessdata.fda.gov", "www.fda.gov", "fda.gov"}
SITE_URL = "https://ghazibot.vercel.app"
KEEP_DAYS = 90
TYPE_AR = {"APPROVAL_ORIGINAL": "موافقة على طلب أصلي", "RECALL": "سحب منتج"}
METHOD_AR = {"exact_normalised_name": "مطابقة الاسم القانوني",
             "reviewed_sponsor_alias": "اسم راعٍ مراجَع لدى FDA"}


def _official(url: Any) -> str | None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    return str(url) if parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS else None


def candidates(report: dict[str, Any], today: date, max_age_days: int) -> list[dict]:
    rows = [*(report.get("approvals") or []), *(report.get("recalls") or [])]
    oldest = (today - timedelta(days=max_age_days)).isoformat()
    picked = [e for e in rows if isinstance(e, dict) and e.get("importance") == "HIGH" and e.get("event_id")
              and e.get("event_type") in TYPE_AR and oldest <= str(e.get("date") or "") <= today.isoformat()]
    return sorted(picked, key=lambda e: (str(e.get("date")), str(e["event_id"])), reverse=True)


def format_message(event: dict[str, Any]) -> str:
    esc = html.escape
    who = str(event.get("sponsor") or event.get("firm") or "—")
    ticker = str(event.get("ticker") or "")
    head = f"<b>{esc(ticker)}</b> · {esc(who)}" if ticker else esc(who)
    lines = [f"🏛️ <b>واقعة FDA رسمية — {esc(TYPE_AR[event['event_type']])}</b>", head]
    if event["event_type"] == "APPROVAL_ORIGINAL":
        products = "، ".join(str(p) for p in event.get("products") or []) or "—"
        lines.append(f"المنتج: {esc(products)} · {esc(str(event.get('application_kind') or ''))} "
                     f"{esc(str(event.get('application_number') or ''))}")
        if event.get("review_priority"):
            lines.append(f"أولوية المراجعة: {esc(str(event['review_priority']))}")
    else:
        lines.append(f"التصنيف: {esc(str(event.get('classification') or '—'))}")
        lines.append(f"المنتج: {esc(str(event.get('product') or '—')[:160])}")
        lines.append(f"السبب: {esc(str(event.get('reason') or '—')[:200])}")
    lines.append(f"تاريخ FDA: {esc(str(event.get('date') or '—'))}")
    lines.append("الرمز: " + (METHOD_AR.get(str(event.get("match_method")), "مطابقة اسم") if ticker
                              else "بلا رمز (لا مطابقة مؤكدة لشركة مدرجة)"))
    official = _official(event.get("official_url"))
    if official:
        lines.append(f'🔗 <a href="{esc(official, quote=True)}">صفحة FDA الرسمية</a>')
    lines.append(f'🔗 <a href="{SITE_URL}/">أحداث FDA على الموقع</a>')
    lines.append("⚠️ واقعة تنظيمية من openFDA (ملك عام CC0) وليست توصية ولا تعني اتجاهًا للسعر؛ "
                 "openFDA يتأخر عن قرار FDA أيامًا.")
    return "\n".join(lines)


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("schema") == STATE_SCHEMA else None


def run(report: dict[str, Any], state: dict[str, Any] | None, *, now: datetime, max_age_days: int,
        max_new: int, send: Callable[[str], Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    today = now.date()
    stamp = now.isoformat()
    picked = candidates(report, today, max_age_days)
    if state is None:
        seen = {e["event_id"]: {"status": "seeded", "date": e.get("date"), "at": stamp} for e in picked}
        new_state = {"schema": STATE_SCHEMA, "seeded_at": stamp, "updated_at": stamp, "events": seen}
        return new_state, {"mode": "seeded", "seeded": len(seen), "sent": 0, "failed": None}
    events = dict(state.get("events") or {})
    sent = 0
    failed = None
    for event in picked:
        if event["event_id"] in events:
            continue
        if sent >= max_new:
            break
        try:
            result = send(format_message(event))
        except Exception as exc:  # noqa: BLE001 - stop on the first delivery failure; unsent events retry next run
            failed = f"{type(exc).__name__}: {str(exc)[:160]}"
            break
        events[event["event_id"]] = {"status": "sent", "date": event.get("date"), "at": stamp,
                                     "message_id": getattr(result, "message_id", None)}
        sent += 1
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    events = {k: v for k, v in events.items() if str((v or {}).get("date") or "9999") >= cutoff}
    new_state = {**state, "updated_at": stamp, "events": events}
    pending = sum(1 for e in picked if e["event_id"] not in events)
    return new_state, {"mode": "delivery", "candidates": len(picked), "sent": sent, "pending": pending, "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--max-age-days", type=int, default=14)
    parser.add_argument("--max-new", type=int, default=5)
    args = parser.parse_args()
    report = json.loads(Path(args.events).read_text(encoding="utf-8"))
    if report.get("schema") != "ghazi.fda_events.v1":
        print("FDA alerts: unexpected events schema; nothing sent.")
        return 1
    sys.path.insert(0, str(ROOT / "scripts"))
    from telegram_transport import send_html_message

    state_path = Path(args.state)
    new_state, summary = run(report, load_state(state_path), now=datetime.now(timezone.utc),
                             max_age_days=args.max_age_days, max_new=args.max_new, send=send_html_message)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print("FDA alerts:", json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
