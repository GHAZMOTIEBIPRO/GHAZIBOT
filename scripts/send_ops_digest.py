"""Telegram operations digest: data-source health, outages and recoveries.

Runs hourly. It sends
- a change alert when a dataset moves between working and not working
  (STALE / SOURCE_UNAVAILABLE / VALIDATION_FAILED / DATA_UNAVAILABLE);
  LICENSE_BLOCKED is a policy state, not an outage, so it never alerts;
- one daily digest (first run at or after 12:00 UTC) with the dataset
  states, official FDA events and the last browser check of the site;
- a delivery test when started with --mode test.

Every message Telegram accepts is recorded with its message_id in the
delivery log; the platform scorecards read that log, so "delivered" means a
message was accepted, not only that the Bot API answered. The workflow is
the single writer of state/telegram/.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ghazi.ops_digest_state.v1"
SITE_URL = "https://ghazibot.vercel.app"
WORKING = {"LIVE", "DELAYED", "HISTORICAL", "RESEARCH_ONLY", "MODEL_ESTIMATED"}
BROKEN = {"STALE", "SOURCE_UNAVAILABLE", "VALIDATION_FAILED", "DATA_UNAVAILABLE"}
STATE_AR = {"LIVE": "حي", "DELAYED": "رسمي مؤجل", "HISTORICAL": "تاريخي", "RESEARCH_ONLY": "بحثي",
            "MODEL_ESTIMATED": "تقديري", "STALE": "قديم", "SOURCE_UNAVAILABLE": "المصدر لا يستجيب",
            "VALIDATION_FAILED": "فشل التحقق", "DATA_UNAVAILABLE": "غير منشور",
            "LICENSE_BLOCKED": "محجوب حتى الترخيص"}
DAILY_HOUR_UTC = 12
LOG_KEEP = 30


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dataset_states(hub: Any) -> dict[str, dict[str, str]]:
    rows = hub.get("datasets") if isinstance(hub, dict) else None
    out = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("file") and row.get("data_state"):
            out[str(row["file"])] = {"state": str(row["data_state"]), "title": str(row.get("title_ar") or row["file"])}
    return out


def transitions(previous: dict[str, str], current: dict[str, dict[str, str]]) -> tuple[list[str], list[str]]:
    """(went down, came back) between working and broken; licence changes are not outages."""
    down, back = [], []
    for file, info in current.items():
        before, now = previous.get(file), info["state"]
        if before is None or before == now:
            continue
        if before in WORKING and now in BROKEN:
            down.append(file)
        elif before in BROKEN and now in WORKING:
            back.append(file)
    return sorted(down), sorted(back)


def _line(info: dict[str, str]) -> str:
    return f"• {html.escape(info['title'])}: {STATE_AR.get(info['state'], html.escape(info['state']))}"


def change_message(down: list[str], back: list[str], current: dict[str, dict[str, str]], now: datetime) -> str:
    lines = ["🛰️ <b>GHAZI RADAR — تغيّر حالة المصادر</b>", f"الوقت: {now:%Y-%m-%d %H:%M} UTC"]
    if down:
        lines.append("⛔ <b>توقف:</b>")
        lines += [_line(current[f]) for f in down]
    if back:
        lines.append("✅ <b>عاد للعمل:</b>")
        lines += [_line(current[f]) for f in back]
    lines += [f'🔗 <a href="{SITE_URL}/">حالة البيانات على الموقع</a>', "تقرير تشغيلي، وليس توصية تداول."]
    return "\n".join(lines)


def daily_message(current: dict[str, dict[str, str]], fda: Any, smoke: Any, now: datetime) -> str:
    counts: dict[str, int] = {}
    for info in current.values():
        counts[info["state"]] = counts.get(info["state"], 0) + 1
    working = sum(v for k, v in counts.items() if k in WORKING)
    broken = [info for info in current.values() if info["state"] in BROKEN]
    lines = ["🛰️ <b>GHAZI RADAR — التقرير التشغيلي اليومي</b>", f"{now:%Y-%m-%d} (UTC)",
             (f"مجموعات البيانات: {len(current)} · تعمل {working}"
              f" · محجوبة بالترخيص {counts.get('LICENSE_BLOCKED', 0)} · متعطلة {len(broken)}")]
    if broken:
        lines.append("⛔ <b>المتعطل الآن:</b>")
        lines += [_line(info) for info in broken[:8]]
    if isinstance(fda, dict):
        c = fda.get("counts") or {}
        lines.append(f"💊 FDA (آخر 30 يومًا): جزيئات جديدة معتمدة {c.get('new_molecule_approvals', '—')}"
                     f" · سحوبات Class I {c.get('class_i_recalls', '—')} · مرتبطة برمز {c.get('matched_to_ticker', '—')}")
    pages = smoke.get("pages") if isinstance(smoke, dict) else None
    if isinstance(pages, dict) and pages:
        ok = sum(1 for p in pages.values() if isinstance(p, dict) and p.get("http_status") == 200 and not p.get("errors"))
        lines.append(f"🌐 الموقع: {ok}/{len(pages)} صفحة بلا أخطاء (فحص {html.escape(str(smoke.get('generated_at', '—'))[:16])})")
    lines += [f'🔗 <a href="{SITE_URL}/">GHAZI RADAR</a>',
              "تقرير تشغيلي عن البيانات والمصادر، وليس توصية تداول."]
    return "\n".join(lines)


def run(*, hub: Any, fda: Any, smoke: Any, state: dict[str, Any] | None, now: datetime, mode: str,
        send: Callable[[str], Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state = dict(state or {"schema": SCHEMA})
    current = dataset_states(hub)
    summary: dict[str, Any] = {"mode": mode, "datasets": len(current), "sent": []}
    if not current:
        summary["skipped"] = "no data hub states"
        return state, summary
    previous = state.get("states") or {}
    messages: list[tuple[str, str]] = []
    down, back = transitions(previous, current)
    if down or back:
        messages.append(("change", change_message(down, back, current, now)))
    today = now.date().isoformat()
    if mode == "test":
        messages.append(("test", "🧪 <b>GHAZI RADAR — اختبار تسليم Telegram</b>\n"
                                 + daily_message(current, fda, smoke, now)))
    elif state.get("last_daily") != today and now.hour >= DAILY_HOUR_UTC:
        messages.append(("daily", daily_message(current, fda, smoke, now)))
    log = list(state.get("delivery_log") or [])
    failed = None
    for kind, text in messages:
        try:
            result = send(text)
        except Exception as exc:  # noqa: BLE001 - keep the previous states so the change is retried next run
            failed = f"{type(exc).__name__}: {str(exc)[:160]}"
            break
        log.append({"kind": kind, "sent_at": now.isoformat(), "message_id": getattr(result, "message_id", None)})
        summary["sent"].append(kind)
        if kind == "daily":
            state["last_daily"] = today
    if failed is None:
        state["states"] = {f: info["state"] for f, info in current.items()}
    state.update(schema=SCHEMA, updated_at=now.isoformat(), delivery_log=log[-LOG_KEEP:])
    summary["failed"] = failed
    summary["changes"] = {"down": down, "back": back}
    return state, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--mode", choices=("scheduled", "test"), default="scheduled")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    from telegram_transport import send_html_message

    state, summary = run(hub=_load(args.data_dir / "data_hub.json"), fda=_load(args.data_dir / "fda_events.json"),
                         smoke=_load(args.data_dir / "site_smoke.json"), state=_load(args.state),
                         now=datetime.now(timezone.utc), mode=args.mode, send=send_html_message)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print("Ops digest:", json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
