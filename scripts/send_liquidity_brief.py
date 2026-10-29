"""Send one weekly Arabic liquidity / labour-market context message per new DOL claims week.

Reads the published liquidity_monitor.json (DOL ETA 539, New York Fed reference rates, OFR repo)
and its own state file. Sends nothing when:
- the file is older than MAX_FILE_AGE (an old run must not send),
- the claims block is missing, stale, or a kept previous copy (never a stale alert),
- the claims week was already sent (dedupe by week, not by run),
- a source's Telegram right in data/source_rights.json is not VERIFIED (that source is left out).
Delivery counts only with a Telegram message_id. The text is a fixed template over computed fields:
no forecast, no trade direction, no single-stock flow claim. The New York Fed's required notice
goes with SOFR whenever SOFR is shown.
"""
from __future__ import annotations

import argparse
import html
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ghazi.liquidity_alert_state.v1"
MAX_FILE_AGE = timedelta(hours=36)
BAND_AR = {"LOWER": "أقل من الفترة نفسها قبل عام", "SIMILAR": "قريبة من الفترة نفسها قبل عام",
           "HIGHER": "أعلى من الفترة نفسها قبل عام"}


def _utc(raw: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def _fmt(v: Any) -> str:
    return f"{v:,.0f}" if isinstance(v, int | float) else "—"


def _pct(v: Any) -> str:
    return "—" if not isinstance(v, int | float) else f"{'+' if v >= 0 else '−'}{abs(v):.1f}%"


def telegram_allowed(rights: dict[str, Any], key: str) -> bool:
    entry = ((rights.get("providers") or {}).get(key) or {}).get("rights") or {}
    return (entry.get("telegram_sharing") or {}).get("status") == "VERIFIED"


def usable(block: Any, rights: dict[str, Any]) -> bool:
    return (isinstance(block, dict) and block.get("available") is True and not block.get("stale")
            and not block.get("kept_previous_copy") and telegram_allowed(rights, str(block.get("rights"))))


def message(liq: dict[str, Any], rights: dict[str, Any]) -> str:
    c = liq["claims"]
    e = html.escape
    lines = ["<b>سياق السيولة وسوق العمل الأمريكي — أسبوعي</b>",
             "<i>سياق اقتصادي عام وليس إشارة شراء أو بيع لأي سهم.</i>", "",
             (f"<b>طلبات إعانة البطالة الأولية</b> (غير معدّلة موسميًا) لأسبوع {e(c['week_ending'])}: "
              f"{_fmt(c.get('initial_claims'))}"),
             f"• الأسبوع نفسه قبل عام: {_fmt(c.get('initial_claims_year_ago'))} ({_pct(c.get('initial_claims_yoy_pct'))})",
             (f"• متوسط 4 أسابيع: {_fmt(c.get('initial_claims_4wk_avg'))} مقابل "
              f"{_fmt(c.get('initial_claims_4wk_avg_year_ago'))} قبل عام ({_pct(c.get('initial_claims_4wk_yoy_pct'))})")]
    band = BAND_AR.get(str(c.get("band_4wk_vs_year_ago")))
    if band:
        lines.append(f"• القراءة: {band} (قاعدة الوصف: فرق ±5% على متوسط 4 أسابيع).")
    if isinstance(c.get("continued_weeks_claimed"), int):
        lines.append(f"• الطلبات المستمرة لأسبوع {e(str(c.get('continued_reflect_week')))}: "
                     f"{_fmt(c['continued_weeks_claimed'])} ({_pct(c.get('continued_yoy_pct'))} على أساس سنوي)")
    lines.append(f"المصدر: وزارة العمل الأمريكية (ETA 539)، حُدّث الملف {e(str(c.get('source_last_modified')))}.")
    notices = []
    f = liq.get("funding_rates")
    if usable(f, rights) and isinstance((f.get("sofr") or {}).get("rate"), int | float):
        rng = f.get("target_range") or []
        within = (f"ضمن النطاق المستهدف {rng[0]:.2f}–{rng[1]:.2f}%" if len(rng) == 2
                  and all(isinstance(x, int | float) for x in rng) else "")
        lines += ["", f"<b>SOFR</b> بتاريخ {e(f['sofr']['date'])}: {f['sofr']['rate']:.2f}% {within}".rstrip()]
        if isinstance(f.get("days_p99_above_target_top"), int) and f.get("window_days"):
            lines.append(f"• أيام تجاوز فيها المئين 99 لـSOFR سقف النطاق: {f['days_p99_above_target_top']} "
                         f"من آخر {f['window_days']} يوم عمل.")
        lines.append("المصدر: بنك الاحتياطي الفيدرالي في نيويورك.")
        notices += [(f.get("notice") or {}).get("SOFR"), (f.get("notice") or {}).get("dtcc")]
    r = liq.get("repo")
    tri = (r or {}).get("tri_party_rate") if isinstance(r, dict) else None
    if usable(r, rights) and isinstance(tri, dict) and tri.get("available") and not tri.get("stale"):
        change = f" (تغير {tri['change_bp']:+.0f} نقطة أساس عن شهر)" if isinstance(tri.get("change_bp"), int | float) else ""
        lines += ["", f"<b>فائدة الريبو الثلاثي لليلة</b> بتاريخ {e(tri['date'])}: {tri['value']:.2f}%{change}",
                  "المصدر: مكتب البحوث المالية (OFR)، بيانات أولية للعلم فقط."]
    if notices := [n for n in notices if n]:
        lines += ["", "<i>" + e(" ".join(notices)) + "</i>"]
    return "\n".join(lines)


def run(liq: dict[str, Any], rights: dict[str, Any], state: dict[str, Any] | None, *, now: datetime,
        send: Callable[[str], Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state = state if isinstance(state, dict) and state.get("schema") == SCHEMA else {"schema": SCHEMA}
    generated = _utc(liq.get("generated_at"))
    if generated is None or not timedelta(0) <= now - generated <= MAX_FILE_AGE:
        return state, {"mode": "stale_or_invalid_file", "sent": 0}
    claims = liq.get("claims")
    if not usable(claims, rights) or not claims.get("week_ending"):
        return state, {"mode": "claims_not_fresh", "sent": 0,
                       "reason": (claims or {}).get("kept_reason") or (claims or {}).get("reason")
                       or ("stale" if (claims or {}).get("stale") else "unavailable_or_rights")}
    week = str(claims["week_ending"])
    if state.get("last_claims_week") == week:
        return state, {"mode": "already_sent", "sent": 0, "week": week}
    try:
        result = send(message(liq, rights))
    except Exception as error:  # noqa: BLE001 - never mark a week sent before Telegram confirms
        return state, {"mode": "failed", "sent": 0, "failed": type(error).__name__}
    receipt = getattr(result, "message_id", None)
    if type(receipt) is not int or receipt <= 0:
        return state, {"mode": "delivery_unconfirmed", "sent": 0, "failed": "NO_TELEGRAM_MESSAGE_ID"}
    return ({**state, "last_claims_week": week, "sent_at": now.isoformat(timespec="seconds"),
             "message_id": receipt, "sofr_date": ((liq.get("funding_rates") or {}).get("sofr") or {}).get("date")},
            {"mode": "sent", "sent": 1, "week": week})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--liquidity", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--rights", type=Path, default=ROOT / "data" / "source_rights.json")
    args = parser.parse_args()
    try:
        liq = json.loads(args.liquidity.read_text(encoding="utf-8"))
        rights = json.loads(args.rights.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Liquidity Telegram: input missing or invalid; nothing sent.")
        return 1
    try:
        old = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    from scripts.telegram_transport import send_html_message
    new_state, summary = run(liq, rights, old, now=datetime.now(timezone.utc), send=send_html_message)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    temp = args.state.with_suffix(".tmp")
    temp.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(args.state)
    print("Liquidity Telegram:", json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
