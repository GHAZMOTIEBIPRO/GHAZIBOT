"""Telegram research watch for newly published official issuer catalysts.

This complements the existing FDA HIGH-event alerts; it only sends MEDIUM FDA
or SEC issuer-context events, and has its own single-writer state in the
catalyst-watchlist workflow. It neither uses quotes nor issues CALL/PUT signals.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from scripts.catalyst_health_context import health_context
from scripts.telegram_transport import send_html_message

SCHEMA = "ghazi.catalyst_watch_alert_state.v1"
REPORT = "ghazi.catalyst_watchlist.v1"
ALLOWED = {"FDA_SUPPLEMENT", "FDA_APPROVAL", "FDA_RECALL",
           "DILUTION_RISK", "LISTING_NOTICE", "MATERIAL_AGREEMENT",
           "EARNINGS_RELEASE", "CHARTER_OR_REVERSE_SPLIT_REVIEW"}
SITE = "https://ghazibot.vercel.app/catalyst-desk.html"


def official_url(url: Any, source: str) -> str | None:
    try:
        value = str(url or "")
        parsed = urlparse(value)
        host = parsed.hostname
        if parsed.scheme != "https" or parsed.username or parsed.password:
            return None
        if source == "openFDA" and host in {
            "accessdata.fda.gov", "www.accessdata.fda.gov", "fda.gov", "www.fda.gov"
        }:
            return value
        if source == "SEC EDGAR" and host in {"sec.gov", "www.sec.gov"}:
            return value
    except ValueError:
        pass
    return None


def _as_utc(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def candidates(report: dict[str, Any], *, now: datetime,
               maximum_event_age_days: int = 10) -> list[dict[str, Any]]:
    """Use dated official source events only; excludes existing FDA HIGH alerts."""
    if (report.get("schema") != REPORT or report.get("research_only") is not True
            or report.get("decision_authority") is not False
            or report.get("execution_authority") is not False
            or not isinstance(report.get("watchlist"), list)
            or len(report["watchlist"]) > 40):
        return []
    produced = _as_utc(report.get("generated_at"))
    if produced is None or not timedelta(0) <= now - produced <= timedelta(hours=72):
        return []
    permitted = report.get("sources") or {}
    oldest = (now.date() - timedelta(days=maximum_event_age_days)).isoformat()
    unique: dict[str, dict[str, Any]] = {}
    for issuer in report["watchlist"]:
        if not isinstance(issuer, dict):
            continue
        symbol = str(issuer.get("symbol") or "")
        if not symbol.isascii() or not symbol.isupper() or not 1 <= len(symbol) <= 8:
            continue
        for event in (issuer.get("catalysts") or [])[:6]:
            if not isinstance(event, dict) or event.get("symbol") != symbol:
                continue
            kind = str(event.get("kind") or "")
            source = str(event.get("source") or "")
            importance = str(event.get("importance") or "")
            day = str(event.get("date") or "")
            if (kind not in ALLOWED or importance not in {"HIGH", "MEDIUM"}
                    or not oldest <= day <= now.date().isoformat()):
                continue
            # High FDA events are already owned by send_fda_alerts.py.
            if source == "openFDA" and (not permitted.get("openfda") or importance != "MEDIUM"):
                continue
            if source == "SEC EDGAR" and permitted.get("sec_edgar") is not True:
                continue
            if source not in {"openFDA", "SEC EDGAR"}:
                continue
            url = official_url(event.get("source_url"), source)
            if url is None:
                continue
            label = str(event.get("label") or "")[:150]
            if not label.strip():
                continue
            raw = f"{symbol}|{source}|{kind}|{day}|{url}|{label}"
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
            unique[digest] = {
                "key": digest, "symbol": symbol, "source": source,
                "date": day, "kind": kind, "importance": importance,
                "label": label, "url": url,
                "dilution_risk": issuer.get("dilution_risk") is True,
            }
    return sorted(unique.values(),
                  key=lambda row: (row["date"], row["importance"] == "HIGH", row["symbol"]),
                  reverse=True)


def message(event: dict[str, Any]) -> str:
    e = lambda value: html.escape(str(value), quote=True)
    tag = "خطر إفصاح" if event["dilution_risk"] else "متابعة تنظيمية"
    return "\n".join([
        "📌 <b>GHAZI RADAR | محفز رسمي جديد</b>",
        f"<b>{e(event['symbol'])}</b> · {e(tag)} · {e(event['source'])}",
        f"نوع: {e(event['kind'])} · أهمية للمتابعة: {e(event['importance'])}",
        f"الحدث: {e(event['label'])}",
        f"تاريخ القرار/الإفصاح: {e(event['date'])}",
        f'<a href="{e(event["url"])}">الوثيقة الرسمية</a> · <a href="{SITE}">رادار المحفزات</a>',
        "⚠️ لا تتوفر أسعار تنفيذ أو تأكيد اتجاه CALL/PUT من هذا الخبر. ليست توصية شراء.",
    ])


def readiness_message(report: dict[str, Any]) -> str:
    """Once-only operational confirmation, never a stock/option signal."""
    total = len(report.get("watchlist") or [])
    providers = report.get("sources") or {}
    fda = "متاح" if providers.get("openfda") is True else "غير متاح"
    sec = "متاح" if providers.get("sec_edgar") is True else "غير متاح"
    created = html.escape(str(report.get("generated_at") or "غير محدد")[:35])
    return "\n".join([
        "✅ <b>GHAZI RADAR | تم ربط رادار المحفزات الرسمي</b>",
        f"شركات في التقرير: <b>{total}</b> (قائمة متابعة تنظيمية، لا إشارات تداول)",
        f"openFDA: <b>{fda}</b> · SEC EDGAR: <b>{sec}</b>",
        f"تاريخ تقرير البيانات: {created}",
        f'<a href="{SITE}">فتح الرادار على الموقع</a>',
        "⚠️ لا توجد أسعار تنفيذية مثبتة من هذه الأحداث؛ CALL/PUT لا يتحدد من الخبر وحده.",
        "التنبيهات التالية تخص أحداثًا رسمية جديدة مؤهلة فقط، مع منع تكرارها.",
    ])

def run(report: dict[str, Any], state: dict[str, Any] | None, *,
        now: datetime, send: Callable[[str], Any],
        maximum_new: int = 3, notify_ready: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    found = candidates(report, now=now)
    stamp = now.isoformat()
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        observed = {item["key"]: {"date": item["date"], "status": "seeded"}
                    for item in found}
        return {"schema": SCHEMA, "seeded_at": stamp,
                "updated_at": stamp, "seen": observed}, {
                    "mode": "seeded", "sent": 0, "candidates": len(found)}
    seen = dict(state.get("seen") or {})
    sent = 0
    failed = None
    ready_notice_sent = False
    produced = _as_utc(report.get("generated_at"))
    valid_report = (
        report.get("schema") == REPORT
        and report.get("research_only") is True
        and report.get("decision_authority") is False
        and report.get("execution_authority") is False
        and isinstance(report.get("watchlist"), list)
        and produced is not None
        and timedelta(0) <= now - produced <= timedelta(hours=72)
    )
    if notify_ready and not state.get("ready_notice_at") and valid_report:
        try:
            result = send(readiness_message(report))
        except Exception as error:  # noqa: BLE001 - retry on a later validated run
            return state, {"mode": "notification_failed", "sent": 0,
                           "ready_notice_sent": False, "failed": type(error).__name__}
        state = {**state, "ready_notice_at": stamp,
                 "ready_notice_message_id": getattr(result, "message_id", None)}
        ready_notice_sent = True
    for item in found:
        if item["key"] in seen:
            continue
        if sent >= max(0, min(maximum_new, 5)):
            break
        try:
            result = send(message(item))
        except Exception as error:  # noqa: BLE001 - preserve unsent events for retry
            failed = type(error).__name__
            break
        seen[item["key"]] = {"date": item["date"], "status": "sent",
                             "message_id": getattr(result, "message_id", None)}
        sent += 1
    cutoff = (now.date() - timedelta(days=90)).isoformat()
    seen = {key: value for key, value in seen.items()
            if isinstance(value, dict) and str(value.get("date") or "") >= cutoff}
    return {**state, "updated_at": stamp, "seen": seen}, {
        "mode": "delivered", "sent": sent, "ready_notice_sent": ready_notice_sent,
        "eligible": len(found), "pending": sum(item["key"] not in seen for item in found),
        "failed": failed,
    }



DIGEST_TZ = ZoneInfo("Asia/Riyadh")
DIGEST_TYPES = {
    "FDA_APPROVAL": "موافقة دوائية", "FDA_SUPPLEMENT": "تحديث موافقة",
    "FDA_RECALL": "سحب منتج", "DILUTION_RISK": "خطر تخفيف ملكية",
    "CHARTER_OR_REVERSE_SPLIT_REVIEW": "تعديل حقوق/تقسيم عكسي",
    "LISTING_NOTICE": "إشعار إدراج", "MATERIAL_AGREEMENT": "اتفاقية",
    "EARNINGS_RELEASE": "نتائج مالية", "INSIDER_FILING": "ملكية مطلعين",
    "PERIODIC_REPORT": "تقرير دوري",
}


def daily_brief_candidates(report: dict[str, Any], *, now: datetime,
                           max_age_days: int = 14) -> list[dict[str, Any]]:
    """Recent official *facts*, max one headline per ticker, not price signals."""
    produced = _as_utc(report.get("generated_at"))
    if (
        report.get("schema") != REPORT
        or report.get("research_only") is not True
        or report.get("decision_authority") is not False
        or report.get("execution_authority") is not False
        or produced is None
        or not timedelta(0) <= now - produced <= timedelta(hours=48)
        or not isinstance(report.get("watchlist"), list)
        or len(report["watchlist"]) > 40
    ):
        return []
    source_flags = report.get("sources") or {}
    oldest = (now.date() - timedelta(days=max_age_days)).isoformat()
    by_symbol: dict[str, dict[str, Any]] = {}
    for issuer in report["watchlist"]:
        if not isinstance(issuer, dict):
            continue
        symbol = str(issuer.get("symbol") or "")
        if not symbol.isascii() or not symbol.isupper() or not 1 <= len(symbol) <= 8:
            continue
        selected: list[dict[str, Any]] = []
        for event in (issuer.get("catalysts") or [])[:6]:
            if not isinstance(event, dict) or event.get("symbol") != symbol:
                continue
            source = str(event.get("source") or "")
            if ((source == "openFDA" and source_flags.get("openfda") is not True)
                    or (source == "SEC EDGAR" and source_flags.get("sec_edgar") is not True)
                    or source not in {"openFDA", "SEC EDGAR"}):
                continue
            importance = str(event.get("importance") or "")
            kind = str(event.get("kind") or "")
            day = str(event.get("date") or "")
            if importance not in {"HIGH", "MEDIUM"} or kind not in DIGEST_TYPES:
                continue
            try:
                event_date = date.fromisoformat(day)
            except ValueError:
                continue
            if not oldest <= event_date.isoformat() <= now.date().isoformat():
                continue
            url = official_url(event.get("source_url"), source)
            if not url:
                continue
            selected.append({
                "symbol": symbol, "kind": kind, "importance": importance,
                "date": day, "url": url, "source": source,
                "label": str(event.get("label") or "")[:100],
                "risk": issuer.get("dilution_risk") is True or kind == "FDA_RECALL",
            })
        if selected:
            selected.sort(key=lambda item: (item["importance"] == "HIGH", item["date"]), reverse=True)
            by_symbol[symbol] = selected[0]
    return sorted(by_symbol.values(),
                  key=lambda item: (item["importance"] == "HIGH", item["date"]),
                  reverse=True)[:8]


def daily_brief_message(report: dict[str, Any], picks: list[dict[str, Any]],
                        *, now: datetime, market_health: Any = None) -> str:
    today = now.astimezone(DIGEST_TZ).date().isoformat()
    sources = report.get("sources") or {}
    source_status = ("openFDA متاح" if sources.get("openfda") is True else "openFDA غير متاح")
    source_status += (" | SEC متاح" if sources.get("sec_edgar") is True else " | SEC غير متاح")
    lines = [
        f"🗓 <b>GHAZI RADAR | الملخص الرسمي اليومي | {today}</b>",
        f"المصادر: {html.escape(source_status)}",
        "هذه أحداث تنظيمية من أيام سابقة حسب التواريخ أدناه، وليست أخبار سعرية لحظية.",
    ]
    verified = health_context(market_health, now=now)
    if verified["available"]:
        lines.append(
            f"حالة نظام المصادر: {html.escape(verified['status_ar'])} "
            f"| تقرير {html.escape(verified['source_time'])}"
        )
        lines.append(f"الأوبشن: {html.escape(verified['options_ar'])}")
        lines.append(f"SEC: {html.escape(verified['sec_ar'])}")
        if verified["blockers"]:
            lines.append("أسباب المنع: " + html.escape(" | ".join(verified["blockers"])))
    else:
        lines.append("صحة محركات الأسعار والأوبشن: تقرير حديث غير متاح؛ لا إثبات تشغيل حي.")
    if not picks:
        lines.append("لا أحداث رسمية حديثة مؤهلة في المصادر المتاحة خلال نافذة هذا التقرير.")
    for item in picks:
        kind = DIGEST_TYPES[item["kind"]]
        caution = " | مراجعة مخاطر" if item["risk"] else ""
        lines.append(
            f"• <b>{html.escape(item['symbol'])}</b> | {html.escape(kind)}"
            f" | {html.escape(item['date'])}{caution}"
            f" | <a href=\"{html.escape(item['url'], quote=True)}\">المصدر</a>"
        )
    lines.extend([
        f'<a href="{SITE}">تصفح المحفزات والشارتات</a>',
        ("⚠️ لا توجد أسعار أو عقود تنفيذية متحققة من هذه الوقائع. "
         "الأهمية ترتيب للمتابعة وليست توقع ارتفاع أو توصية CALL/PUT."),
    ])
    return "\n".join(lines)


def send_daily_brief(report: dict[str, Any], state: dict[str, Any], *,
                     now: datetime, send: Callable[[str], Any],
                     market_health: Any = None
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    day = now.astimezone(DIGEST_TZ).date().isoformat()
    if now.astimezone(DIGEST_TZ).weekday() >= 5:
        return state, {"mode": "weekend", "sent": 0}
    if state.get("daily_brief_date") == day:
        return state, {"mode": "already_sent", "sent": 0}
    picks = daily_brief_candidates(report, now=now)
    # No fresh source report means not even a health-only daily summary.
    generated = _as_utc(report.get("generated_at"))
    report_valid = (
        report.get("schema") == REPORT
        and report.get("research_only") is True
        and report.get("decision_authority") is False
        and report.get("execution_authority") is False
        and isinstance(report.get("watchlist"), list)
        and len(report["watchlist"]) <= 40
        and generated is not None
        and timedelta(0) <= now - generated <= timedelta(hours=48)
    )
    if not report_valid:
        return state, {"mode": "stale_or_invalid_official_report", "sent": 0}
    if not picks and not health_context(market_health, now=now)["available"]:
        return state, {"mode": "no_verified_recent_events", "sent": 0}
    try:
        result = send(daily_brief_message(report, picks, now=now, market_health=market_health))
    except Exception as error:  # noqa: BLE001 - never mark success before Telegram confirms
        return state, {"mode": "failed", "sent": 0, "failed": type(error).__name__}
    return {
        **state, "daily_brief_date": day, "daily_brief_at": now.isoformat(),
        "daily_brief_message_id": getattr(result, "message_id", None),
    }, {"mode": "sent", "sent": 1, "symbols": len(picks)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--market-health", type=Path,
                        help="Previously published market/option operational status (not quotes).")
    parser.add_argument("--daily-brief", action="store_true",
                        help="Send one Riyadh-dated daily official catalyst research summary.")
    parser.add_argument("--notify-ready", action="store_true",
                        help="Send one operational connection confirmation after seeding.")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Catalyst Telegram: source report missing or invalid.")
        return 1
    try:
        old = json.loads(args.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        old = None
    new_state, summary = run(report, old, now=datetime.now(timezone.utc),
                             send=send_html_message, notify_ready=args.notify_ready)
    digest = {}
    if args.daily_brief and not summary.get("failed") and new_state.get("schema") == SCHEMA:
        health_report = {}
        if args.market_health is not None:
            try:
                health_report = json.loads(args.market_health.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        new_state, digest = send_daily_brief(
            report, new_state, now=datetime.now(timezone.utc),
            send=send_html_message, market_health=health_report
        )
    args.state.parent.mkdir(parents=True, exist_ok=True)
    temp = args.state.with_suffix(".tmp")
    temp.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(args.state)
    print("Catalyst Telegram:", json.dumps({"events": summary, "daily": digest}, ensure_ascii=False))
    return 1 if summary.get("failed") or digest.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
