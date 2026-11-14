"""Source-backed, license-safe context for GHAZI RADAR signals and weekly brief.

Consumes *already published public event files* from bot-state. No HTTP, LLM,
market-data feeds, price predictions or broker execution. An event is never a
directional trade signal. Staleness, source URL and event date are mandatory.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ALLOWED_PUBLIC_SCHEMAS = {
    "week_agenda": "ghazi.week_agenda.v1",
    "ir_news": "ghazi.ir_news.v1",
    "catalyst_watchlist": "ghazi.catalyst_watchlist.v1",
}
MAX_FEED_AGE_HOURS = {"week_agenda": 96, "ir_news": 72, "catalyst_watchlist": 72}
TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
MAX_EVENTS_BY_TICKER = 3
OFFICIAL_EVENT_SOURCES = {"Federal Register", "ClinicalTrials.gov", "SEC EDGAR", "Company IR", "openFDA"}


def _date(value: Any) -> date | None:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None
        return date.fromisoformat(value)
    except ValueError:
        return None


def _stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def _url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 700:
        return None
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.netloc or
            parsed.username or parsed.password or parsed.fragment):
        return None
    host = (parsed.hostname or "").lower()
    if (not host or "." not in host or host.endswith(".local") or
            host in {"localhost", "127.0.0.1"}):
        return None
    return value


def _source_file(path: Path, expected_schema: str, *, now: datetime, max_hours: int) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > 3_000_000:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != expected_schema:
        return None
    generated = _stamp(raw.get("generated_at"))
    if generated is None:
        return None
    age = (now - generated).total_seconds()
    if age < -600 or age > max_hours * 3600:
        return None
    # Workflows occasionally keep a previous unsuccessful output; distinguish
    # source availability from its existence.
    if str(raw.get("status", "AVAILABLE")).upper() in {"UNAVAILABLE", "FAILED", "ERROR"}:
        return None
    return raw


def collect_official_events(
    directory: Path, *, now: datetime, symbols: list[str],
    future_days: int = 7, recent_days: int = 3,
) -> dict[str, Any]:
    """Return dated, source-linked official context (never causal/price labels).

    Sources may be stale/missing. Returned availability tracks each source
    independently and NO headline is invented when a feed is absent.
    """
    if now.tzinfo is None:
        raise ValueError("aware UTC time required")
    now = now.astimezone(timezone.utc)
    today = now.date()
    symbol_set = {x.upper() for x in symbols if isinstance(x, str) and TICKER.fullmatch(x.upper())}
    sources: dict[str, str] = {}
    found: list[dict[str, Any]] = []
    used_ids: set[tuple[str, str, str]] = set()

    def add(row: dict[str, Any]) -> None:
        symbol = str(row.get("symbol", "")).upper().strip()
        when = _date(row.get("date"))
        link = _url(row.get("url"))
        label = str(row.get("title") or "").strip()
        if symbol not in symbol_set or when is None or link is None or not label:
            return
        key = (symbol, link, str(when))
        if key in used_ids:
            return
        used_ids.add(key)
        found.append({
            "symbol": symbol, "date": str(when),
            "kind": str(row.get("kind") or "OFFICIAL_REVIEW"),
            "title": label[:160], "source": str(row.get("source") or "مصدر رسمي")[:50],
            "url": link, "priority": int(row.get("priority", 1)),
            "upcoming": when >= today,
        })

    for name, schema in ALLOWED_PUBLIC_SCHEMAS.items():
        source = _source_file(
            directory / f"{name}.json", schema, now=now,
            max_hours=MAX_FEED_AGE_HOURS[name],
        )
        sources[name] = "AVAILABLE" if source is not None else "UNAVAILABLE_OR_STALE"
        if source is None:
            continue
        if name == "week_agenda":
            items = source.get("items")
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                day = _date(item.get("date"))
                if (day is None or not today <= day <= today + timedelta(days=future_days)
                        or item.get("basis") != "COMPANY_ANNOUNCED"
                        or str(item.get("source") or "").lower() != "company ir"):
                    continue
                add({"symbol": item.get("symbol"), "date": str(day),
                     "kind": "UPCOMING_COMPANY_EVENT",
                     "title": item.get("title_ar") or item.get("title") or "موعد شركة",
                     "source": "Company IR", "url": item.get("source_url"), "priority": 100})
        elif name == "ir_news":
            items = source.get("items")
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or item.get("source_kind") != "press_release":
                    continue
                stamp = _stamp(item.get("source_published_at"))
                if stamp is None or not (now - timedelta(days=recent_days) <= stamp <= now):
                    continue
                add({"symbol": item.get("symbol"), "date": stamp.date().isoformat(),
                     "kind": "ISSUER_NEWS_REVIEW",
                     "title": item.get("title"), "source": "Company IR",
                     "url": item.get("url"), "priority": 50})
        elif name == "catalyst_watchlist":
            events = source.get("events")
            for item in events if isinstance(events, list) else []:
                if not isinstance(item, dict) or item.get("source") not in OFFICIAL_EVENT_SOURCES:
                    continue
                day = _date(item.get("date"))
                if day is None or day > today or day < today - timedelta(days=recent_days):
                    continue
                add({"symbol": item.get("symbol"), "date": str(day),
                     "kind": "OFFICIAL_RECORD_REVIEW",
                     "title": item.get("label") or item.get("reason"),
                     "source": item.get("source"), "url": item.get("source_url"),
                     "priority": 20})

    # Upcoming dated company commitments first, then recently published news.
    found.sort(key=lambda x: (-x["priority"], x["date"] if x["upcoming"] else "", x["symbol"]))
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in found:
        rows = by_symbol.setdefault(item["symbol"], [])
        if len(rows) < MAX_EVENTS_BY_TICKER:
            rows.append(item)
    return {"by_symbol": by_symbol, "sources": sources, "event_count": sum(map(len, by_symbol.values())),
            "generated_at": now.isoformat(), "research_only": True}


def _event_html(item: dict[str, Any]) -> str:
    date_ar = html.escape(item["date"])
    if item["kind"] == "UPCOMING_COMPANY_EVENT":
        kind = "موعد رسمي مقبل"
    elif item["kind"] == "ISSUER_NEWS_REVIEW":
        kind = "خبر من الشركة"
    else:
        kind = "سجل رسمي للمراجعة"
    title = html.escape(item["title"][:75])
    link = html.escape(item["url"], quote=True)
    return f"{kind} {date_ar}: <a href=\"{link}\">{title}</a>"


def fib_context_lines(context: dict[str, Any], *, symbols: list[str], limit: int = 4) -> list[str]:
    """Compact official context for a daily private signal message."""
    if not isinstance(context, dict):
        return []
    by_symbol = context.get("by_symbol") or {}
    lines: list[str] = []
    for symbol in symbols:
        rows = by_symbol.get(symbol) if isinstance(by_symbol, dict) else []
        if not isinstance(rows, list) or not rows:
            continue
        for event in rows[:1]:
            if isinstance(event, dict):
                lines.append(f"<b>{html.escape(symbol)}</b>: {_event_html(event)}")
                if len(lines) >= limit:
                    break
        if len(lines) >= limit:
            break
    if not lines:
        return ["الأخبار الرسمية: لا أحداث حديثة مرتبطة بالمرشحين في المصادر المتاحة؛ لا يعني غياب الأخبار."]
    return ["<b>أحداث رسمية مرتبطة بالمراقبة (لا تحدد اتجاه السعر):</b>", *lines,
            "تنبيه: الخبر والموعد لا يؤكدان CALL/PUT ولا يضمنان سيولة عقد الخيارات."]


def render_weekly_official_brief(
    context: dict[str, Any], *, now: datetime, max_items: int = 8,
) -> str:
    """Weekly owner-private plain Telegram HTML report, without licensed prices."""
    if now.tzinfo is None:
        raise ValueError("aware clock required")
    by_symbol = context.get("by_symbol", {}) if isinstance(context, dict) else {}
    records: list[dict[str, Any]] = []
    for rows in by_symbol.values() if isinstance(by_symbol, dict) else []:
        if isinstance(rows, list):
            records.extend(x for x in rows if isinstance(x, dict))
    upcoming = sorted((x for x in records if x.get("kind") == "UPCOMING_COMPANY_EVENT"),
                      key=lambda x: (x["date"], x["symbol"]))[:max_items]
    recent = sorted((x for x in records if x.get("kind") == "ISSUER_NEWS_REVIEW"),
                    key=lambda x: (x["date"], x["symbol"]), reverse=True)[:3]
    lines = [
        f"<b>غازي رادار | تقرير الأسبوع {now.date().isoformat()}</b>",
        "المرجع: تقاويم علاقات المستثمرين والأخبار الرسمية المنشورة؛ بلا أسعار سوق أو توصيات عقود.",
    ]
    if upcoming:
        lines.append("<b>المواعيد القادمة المعلنة من الشركات:</b>")
        for event in upcoming:
            lines.append(f"<b>{html.escape(event['symbol'])}</b>: {_event_html(event)}")
    else:
        lines.append("لم يتوفر موعد شركة مؤكد ضمن نطاق مصادر التقويم الحالية.")
    if recent:
        lines.append("<b>أحدث بيانات علاقات المستثمرين:</b>")
        for event in recent:
            lines.append(f"<b>{html.escape(event['symbol'])}</b>: {_event_html(event)}")
    sources = context.get("sources", {}) if isinstance(context, dict) else {}
    usable = sum(v == "AVAILABLE" for v in sources.values()) if isinstance(sources, dict) else 0
    lines.extend([
        f"حالة المصادر: {usable} من {len(ALLOWED_PUBLIC_SCHEMAS)} صالحة زمنيًا وقت إعداد التقرير.",
        "هذه قائمة أحداث للمراقبة فقط؛ تحقق من التفاصيل والساعة من المصدر قبل أي قرار.",
    ])
    while len("\n".join(lines)) > 3800 and len(lines) > 4:
        lines.pop(-3)  # shed lowest-priority recent context; preserve disclaimers
    return "\n".join(lines)
