"""Keyless GHAZI RADAR daily official market context for Telegram.

Consumes already-published *official* CFTC, Treasury and issuer IR evidence.
Makes no external market-data calls, uses no API key, never substitutes ETF
option quotes or claims dealer gamma/flow. Source event dates are explicit.
Delivery is once each Riyadh weekday after 08:15 and requires a Telegram
positive message_id before suppressing retries. No message on stale evidence.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from scripts.telegram_transport import send_html_message

RIYADH = ZoneInfo("Asia/Riyadh")
CORE_COMPANIES = frozenset(("TSLA", "AMD", "MU", "NVDA", "MSFT", "BABA",
                             "GOOG", "GOOGL", "META"))
OFFICIAL_IR_HOSTS = frozenset((
    "investor.nvidia.com", "ir.amd.com", "investor.exxonmobil.com",
    "www.intc.com", "ir.netflix.net", "investor.qualcomm.com",
    "investors.coca-colacompany.com", "investorrelations.gd.com",
))
SCHEMA = "ghazi.verified_keyless_brief_state.v1"


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _fresh(document: Any, now: datetime, *, hours: int = 72) -> bool:
    if not isinstance(document, dict):
        return False
    t = _utc(document.get("generated_at"))
    return t is not None and timedelta(0) <= now - t <= timedelta(hours=hours)


def _amount(value: Any) -> int | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return int(value)


def _official_link(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 800:
        return None
    try:
        parts = urlparse(value)
    except ValueError:
        return None
    return (value if parts.scheme == "https" and parts.hostname in OFFICIAL_IR_HOSTS
            and not parts.username and not parts.password else None)


def macro_lines(macro: Any, now: datetime) -> list[str]:
    if not _fresh(macro, now) or macro.get("schema") != "ghazi.public_macro.v1":
        return []
    if macro.get("execution_authority") is not False:
        return []
    out = []
    contexts = macro.get("cftc_index_futures")
    if isinstance(contexts, dict):
        for root, label in (("ES", "S&P 500"), ("NQ", "Nasdaq-100")):
            report = contexts.get(root)
            if not isinstance(report, dict) or report.get("available") is not True:
                continue
            try:
                day = date.fromisoformat(str(report.get("positions_as_of")))
                age = (now.date() - day).days
            except ValueError:
                continue
            if not 0 <= age <= 14:
                continue
            cats = report.get("categories") or {}
            if not isinstance(cats, dict):
                continue
            lev = cats.get("leveraged_funds") or {}
            funds = cats.get("asset_manager") or {}
            if not isinstance(lev, dict) or not isinstance(funds, dict):
                continue
            net = _amount(lev.get("net"))
            change = _amount(lev.get("weekly_change"))
            mgr_net = _amount(funds.get("net"))
            if net is None or change is None or mgr_net is None:
                continue
            out.append(
                f"• <b>CFTC {label}</b> (مراكز آجلة حتى {day.isoformat()}): "
                f"صافي الصناديق ذات الرافعة {net:+,} عقد؛ "
                f"التغير الأسبوعي {change:+,}؛ "
                f"صافي مديري الأصول {mgr_net:+,}."
            )
    curve = macro.get("treasury_curve")
    if isinstance(curve, dict) and curve.get("available") is True:
        try:
            d = date.fromisoformat(str(curve["curve_date"]))
            day_age = (now.date() - d).days
        except (KeyError, ValueError):
            day_age = 999
        yields = curve.get("yields_pct")
        if 0 <= day_age <= 7 and isinstance(yields, dict):
            y10 = yields.get("10Y")
            y2 = yields.get("2Y")
            if (type(y10) in (float, int) and type(y2) in (float, int)
                    and math.isfinite(y10) and math.isfinite(y2)
                    and 0 <= y10 <= 25 and 0 <= y2 <= 25):
                out.append(f"• <b>الخزانة الأمريكية</b> ({d.isoformat()}): "
                           f"عائد 10 سنوات {y10:.2f}%؛ سنتان {y2:.2f}%.")
    return out


def ir_lines(report: Any, now: datetime) -> list[str]:
    if not _fresh(report, now) or report.get("schema") != "ghazi.ir_news.v1":
        return []
    sources = report.get("sources")
    items = report.get("items")
    if not isinstance(sources, list) or not isinstance(items, list):
        return []
    active = {str(s.get("symbol")) for s in sources if isinstance(s, dict)
              and s.get("status") == "OK"}
    valid = []
    for item in items[:200]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if symbol not in CORE_COMPANIES or symbol not in active:
            continue
        link = _official_link(item.get("url"))
        published = _utc(item.get("source_published_at"))
        title = str(item.get("title") or "").strip()
        if not link or not title or len(title) > 240 or published is None:
            continue
        if not timedelta(0) <= now - published <= timedelta(days=7):
            continue
        valid.append((published, symbol, title, link, item.get("event_at")))
    valid.sort(key=lambda x: x[0], reverse=True)
    used: set[str] = set()
    out = []
    for published, symbol, title, link, event_at in valid:
        if symbol in used:
            continue
        used.add(symbol)
        line = (f'• <b>{html.escape(symbol)}</b> '
                f'({published.date().isoformat()}): '
                f'<a href="{html.escape(link, quote=True)}">'
                f'{html.escape(title[:125])}</a>.')
        if isinstance(event_at, str):
            try:
                event_day = date.fromisoformat(event_at)
                if published.date() <= event_day <= now.date() + timedelta(days=120):
                    line += f" موعد الحدث المعلن: {event_day.isoformat()}."
            except ValueError:
                pass
        out.append(line)
        if len(out) == 4:
            break
    return out


def due(now: datetime, state: dict[str, Any]) -> bool:
    local = now.astimezone(RIYADH)
    return (local.weekday() < 5 and (local.hour, local.minute) >= (8, 15)
            and state.get("last_sent_day") != local.date().isoformat())


def build_message(macro: Any, ir: Any, *, now: datetime) -> str | None:
    ml = macro_lines(macro, now)
    il = ir_lines(ir, now)
    if not ml and not il:
        return None
    lines = [
        f"<b>GHAZI RADAR | سياق رسمي مجاني | {now.astimezone(RIYADH).date()}</b>",
        "المصادر: CFTC والخزانة الأمريكية وعلاقات المستثمرين الرسمية.",
        "بيانات CFTC أسبوعية ومتأخرة، وليست جاما عقود الخيارات أو سيولة مؤسسية لحظية.",
    ]
    if ml:
        lines.append("<b>المؤشرات والفائدة</b>")
        lines.extend(ml)
    if il:
        lines.append("<b>أخبار الشركات الأساسية</b>")
        lines.extend(il)
    lines.append("للبحث فقط: لا أسعار تنفيذ للأوبشن ولا توصية CALL/PUT أو توقع حركة مؤكدة.")
    return "\n".join(lines)


def deliver(macro: Any, ir: Any, state: dict[str, Any], *,
            now: datetime, send: Callable[[str], Any] = send_html_message
            ) -> str:
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    if not due(now, state):
        return "NOT_DUE"
    msg = build_message(macro, ir, now=now)
    if msg is None:
        return "NO_FRESH_OFFICIAL_EVIDENCE"
    # Do not mark as sent unless Telegram confirms actual message identity.
    try:
        receipt = send(msg)
    except Exception:
        return "TELEGRAM_SEND_FAILED"
    identifier = getattr(receipt, "message_id", None)
    if type(identifier) is not int or identifier <= 0:
        return "TELEGRAM_UNCONFIRMED"
    state.update({"schema": SCHEMA,
                  "last_sent_day": now.astimezone(RIYADH).date().isoformat(),
                  "last_message_id": identifier,
                  "last_sent_at": now.astimezone(timezone.utc).isoformat()})
    return "TELEGRAM_ACCEPTED"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--macro", required=True, type=Path)
    p.add_argument("--ir-news", required=True, type=Path)
    p.add_argument("--state", required=True, type=Path)
    args = p.parse_args()
    state = _read(args.state)
    result = deliver(_read(args.macro), _read(args.ir_news), state,
                     now=datetime.now(timezone.utc))
    if result == "TELEGRAM_ACCEPTED":
        args.state.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.state.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(args.state)
    print("Official free context bulletin:", result)
    return 0 if result in ("TELEGRAM_ACCEPTED", "NOT_DUE", "NO_FRESH_OFFICIAL_EVIDENCE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
