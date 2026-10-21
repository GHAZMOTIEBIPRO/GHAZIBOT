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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
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
    args.state.parent.mkdir(parents=True, exist_ok=True)
    temp = args.state.with_suffix(".tmp")
    temp.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(args.state)
    print("Catalyst Telegram:", json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
