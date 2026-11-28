"""Public status of the owner-private ORACLE pipeline: statuses and counts only (runtime/public/data/oracle_status.json).

Reads bot-state markers that already hold no market values (report and session slot statuses, the post-close
scorecard counts, the options-hunter alert count, small-cap post-close counts, SEC registry counts, command
statuses) and states each feed's real coverage and delay. No price, level, symbol-level state or contract from
Alpaca data is copied here: Alpaca data is licensed for the owner's internal use, not for publication.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEEDS = [
    {"name": "Alpaca SIP (تاريخي)", "use": "خرائط ما قبل الافتتاح وتحديثات الجلسة", "delay": "16 دقيقة على الأقل",
     "coverage": "كل البورصات الأمريكية", "public": False},
    {"name": "Alpaca IEX (بث لحظي)", "use": "رصد أولي لحظي للمالك", "delay": "ثوانٍ", "coverage": "منصة واحدة (جزئية)",
     "public": False},
    {"name": "Alpaca Options (indicative)", "use": "صياد العقود", "delay": "إرشادي؛ الصفقات متأخرة 15 دقيقة",
     "coverage": "مشتق من OPRA وليس OPRA", "public": False},
    {"name": "SEC EDGAR", "use": "الإفصاحات الرسمية وسجل الشركات", "delay": "دقائق بعد قبول الإفصاح",
     "coverage": "كل المُصدرين المسجلين", "public": True},
]


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _latest_day(root: Path) -> Path | None:
    days = sorted(p for p in root.glob("20??-??-??") if p.is_dir()) if root.exists() else []
    return days[-1] if days else None


def build(state: Path, data: Path, now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": "ghazi.oracle_status.v1", "generated_at": now.isoformat(), "feeds": FEEDS,
                           "note_ar": "حالات وعدادات فقط؛ أسعار Alpaca ومشتقاتها للمالك وحده ولا تُنشر."}
    day = _latest_day(state / "daily_plan")
    if day:
        reports = {}
        for slot in ("EARLY", "FINAL"):
            m = _load(day / f"report_{slot}.json") or {}
            if m:
                reports[slot] = {k: m.get(k) for k in ("status", "late", "late_minutes", "sent_at", "messages", "accepted")}
        session = {}
        for slot in ("OPENING", "LASTHOUR", "POSTCLOSE"):
            m = _load(day / f"session_{slot}.json") or {}
            if m:
                session[slot] = {k: m.get(k) for k in ("status", "sent_at", "messages")}
        scorecard = (_load(day / "session_POSTCLOSE.json") or {}).get("scorecard")
        out["day"] = {"date": day.name, "reports": reports, "session": session, "scorecard": scorecard}
    hunter = _load(state / "options_hunter" / "last_top.json") or {}
    out["options_hunter"] = {"day": hunter.get("day"), "material_alerts": len(hunter.get("alerted") or []),
                             "last_sent_at": hunter.get("sent_at")}
    small = sorted((state / "smallcaps").glob("*.postclose.json")) if (state / "smallcaps").exists() else []
    out["smallcaps"] = {"day": small[-1].name[:10], **(_load(small[-1]) or {})} if small else {"day": None}
    sec = _load(data / "sec_company_tickers.json") or {}
    out["sec_registry"] = ({"status": "OK", "generated_at": sec.get("generated_at"), **(sec.get("counts") or {})}
                           if sec else {"status": "NOT_CONFIGURED", "reason": "SEC_USER_AGENT secret not set"})
    cmds = _load(state / "telegram" / "telegram_commands_offset.json") or {}
    out["commands"] = {"last_at": cmds.get("updated_at"), "last_results": [r.get("status") for r in cmds.get("last_results") or []]}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("../state/state"))
    parser.add_argument("--data", type=Path, default=Path("../state/runtime/public/data"))
    parser.add_argument("--output", type=Path, default=Path("../state/runtime/public/data/oracle_status.json"))
    args = parser.parse_args()
    status = build(args.state, args.data, datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    print("oracle status:", json.dumps({k: status.get(k) for k in ("day", "sec_registry")}, ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
