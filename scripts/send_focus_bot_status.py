"""One bounded daily Telegram operational bulletin for the owner's core US watchlist.

Only non-price metadata is used. This is NOT a contract alert, an OPRA feed,
a trade recommendation, proof of delivery, or permission to publish quotes.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from options_radar.focus_universe import FOCUS_INDICES, FOCUS_STOCKS
from scripts.telegram_transport import send_html_message

RIYADH = ZoneInfo("Asia/Riyadh")
MAX_AGE_MINUTES = 180


def _read(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _fresh(report: dict[str, Any], now: datetime) -> bool:
    try:
        time = datetime.fromisoformat(str(report["generated_at"]).replace("Z", "+00:00"))
        if time.tzinfo is None:
            return False
        age = (now.astimezone(timezone.utc) - time.astimezone(timezone.utc)).total_seconds() / 60
        return 0 <= age <= MAX_AGE_MINUTES
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def due(now: datetime, state: dict[str, Any]) -> bool:
    if now.tzinfo is None:
        return False
    local = now.astimezone(RIYADH)
    # During US-market days only; at least 30 minutes after both US DST/winter opens.
    return (local.weekday() < 5 and 18 <= local.hour < 24
            and state.get("last_sent_day") != local.date().isoformat())


def summarize(
    health: dict[str, Any],
    data_status: dict[str, Any],
    index: dict[str, Any],
    guardian: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    health_ok = _fresh(health, now)
    data_ok = _fresh(data_status, now)
    guardian_ok = _fresh(guardian, now)
    index_ok = _fresh(index, now)
    diagnostics = data_status.get("coverage_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    index_blocked = not index_ok or index.get("status") == "SOURCE_TERMS_BLOCKED"
    production_quotes = (
        health_ok and data_ok
        and health.get("checks", {}).get("option_quotes_production_ready") is True
        and diagnostics.get("options_execution_quote_ready") is True
    )
    return {
        "schema": "ghazi.focus_bot_operational.v1",
        "as_of": now.astimezone(timezone.utc).isoformat(),
        "health_fresh": health_ok,
        "stock_data_fresh": data_ok,
        "index_report_fresh": index_ok,
        "guardian_fresh": guardian_ok,
        "index_data_blocked": index_blocked,
        "production_option_quotes_verified": production_quotes,
        "options_flow_verified": (
            production_quotes and diagnostics.get("options_trade_flow_ready") is True
        ),
        "public_stock_rows": (
            max(0, int(data_status.get("row_counts", {}).get("stocks") or 0))
            if data_ok else None
        ),
        "public_option_rows": (
            max(0, int(data_status.get("row_counts", {}).get("options") or 0))
            if data_ok else None
        ),
        "active_guardian_contracts": (
            max(0, int(guardian.get("active_count") or 0))
            if guardian_ok else None
        ),
        "blocked_sources": list(diagnostics.get("blocking_codes") or [])[:6]
            if data_ok else ["DATA_STATUS_STALE"],
        "health_state": str(health.get("status") or "unknown") if health_ok else "stale_or_missing",
        "decision_authority": False,
    }


def message(summary: dict[str, Any], *, now: datetime) -> str:
    def count(value: Any) -> str:
        return "غير مثبت" if value is None else str(value)
    local = now.astimezone(RIYADH)
    index = "محجوب أو قديم" if summary["index_data_blocked"] else "متوفر للبحث فقط"
    source = "موثقة" if summary["production_option_quotes_verified"] else "غير مؤهلة للتنفيذ"
    flow = "موثقة" if summary["options_flow_verified"] else "غير مثبتة"
    state = html.escape(str(summary["health_state"]))
    blockers = ", ".join(html.escape(str(x)[:50]) for x in summary["blocked_sources"][:4])
    lines = [
        "<b>GHAZI RADAR — تقرير تشغيل البوت</b>",
        f"اليوم: <b>{local.date().isoformat()}</b> | الرياض",
        "",
        "<b>نطاق المتابعة الأساسي</b>",
        "المؤشرات: " + " • ".join(FOCUS_INDICES),
        "الشركات: " + " • ".join(FOCUS_STOCKS),
        "",
        "<b>البيانات المؤهلة</b>",
        "تحليل المؤشرات: " + index,
        "عروض الأوبشن التنفيذية: " + source,
        "تدفقات الأوبشن: " + flow,
        f"سجلات الأسهم المنشورة: {count(summary['public_stock_rows'])}",
        f"سجلات عقود الأوبشن المنشورة: {count(summary['public_option_rows'])}",
        f"عقود المتابعة الفعالة: {count(summary['active_guardian_contracts'])}",
        "صحة محرك البيانات: " + state,
    ]
    if blockers:
        lines.append("عوامل الحجب: " + blockers)
    lines.extend([
        "",
        "<b>لا توجد توصية دخول في هذه الرسالة.</b>",
        "أي CALL/PUT يجب أن يجتاز فحوص صلاحية المصدر وحداثة الأسعار والسيولة وبوابة V11.",
        '<a href="https://ghazir.vercel.app/contract">سجل متابعة العقود</a>',
    ])
    return "\n".join(lines)


def run(
    health: dict[str, Any], data_status: dict[str, Any],
    index: dict[str, Any], guardian: dict[str, Any],
    state: dict[str, Any], *, now: datetime, send=send_html_message,
) -> str:
    if not due(now, state):
        return "NOT_DUE"
    summary = summarize(health, data_status, index, guardian, now=now)
    receipt = send(message(summary, now=now))
    # Do not acknowledge a delivery without a Telegram Bot API receipt.
    identifier = getattr(receipt, "message_id", None)
    if not isinstance(identifier, int) or identifier <= 0:
        raise RuntimeError("Telegram message_id missing: cannot acknowledge daily bulletin")
    state.update({
        "last_sent_day": now.astimezone(RIYADH).date().isoformat(),
        "last_message_id": identifier,
        "last_sent_at": now.astimezone(timezone.utc).isoformat(),
        "last_health_state": summary["health_state"],
        "last_option_quotes_verified": summary["production_option_quotes_verified"],
        "schema": "ghazi.focus_bot_state.v1",
    })
    return "TELEGRAM_ACCEPTED"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--health", type=Path, default=Path("public/data/health.json"))
    p.add_argument("--data-status", type=Path, default=Path("public/data/data-status.json"))
    p.add_argument("--index", type=Path, default=Path(".bot-state/runtime/public/data/index_radar.json"))
    p.add_argument("--guardian", type=Path, default=Path("public/data/contract_guardian.json"))
    p.add_argument("--state", type=Path, default=Path("data/live/focus_bot_status_state.json"))
    args = p.parse_args()
    state = _read(args.state)
    result = run(_read(args.health), _read(args.data_status),
                 _read(args.index), _read(args.guardian),
                 state, now=datetime.now(timezone.utc))
    if result == "TELEGRAM_ACCEPTED":
        _save(args.state, state)
    print(f"GHAZI focus bot bulletin: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
