"""Week agenda: dated items for the next 7 days, each with where its date comes from.

- Exchange days: the official XNYS calendar (exchange_calendars): closed weekdays and early closes.
- Company-announced dates: catalyst events whose company gave a date (official IR event feeds, scheduled_for).
- Federal Register dates the document itself sets for a linked company: when a rule takes effect
  (effective_on) and when comments close (comments_close_on).

No date is inferred or estimated here; an item without a source date is not listed. The agenda is
not a forecast: it says what is scheduled, never what it will mean for a price.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

SCHEMA = "ghazi.week_agenda.v1"
DAYS = 7
NY = "America/New_York"


def _load(path: Path | None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None


def _day(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def exchange_items(start: date, end: date) -> list[dict[str, Any]]:
    cal = xcals.get_calendar("XNYS")
    sessions = {d.date() for d in cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))}
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in sessions:
            out.append({"date": d.isoformat(), "kind": "MARKET_CLOSED", "title_ar": "السوق الأمريكي مغلق (عطلة رسمية)",
                        "basis": "EXCHANGE_CALENDAR"})
        elif d in sessions:
            close = cal.session_close(pd.Timestamp(d)).tz_convert(NY)
            if (close.hour, close.minute) < (16, 0):
                out.append({"date": d.isoformat(), "kind": "EARLY_CLOSE", "basis": "EXCHANGE_CALENDAR",
                            "time_et": close.strftime("%H:%M"),
                            "title_ar": f"إغلاق مبكر للسوق الأمريكي الساعة {close.strftime('%H:%M')} بتوقيت نيويورك"})
        d += timedelta(days=1)
    return out


def company_items(catalysts: Any, start: date, end: date) -> list[dict[str, Any]]:
    out, seen = [], set()
    for e in (catalysts or {}).get("events") or []:
        when = _day(e.get("scheduled_for"))
        if not when or not (start.isoformat() <= when <= end.isoformat()):
            continue
        key = (e.get("symbol"), when, e.get("source_url"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": when, "kind": "COMPANY_SCHEDULE", "symbol": e.get("symbol"), "basis": "COMPANY_ANNOUNCED",
                    "title": str(e.get("reason") or "")[:200], "title_ar": "موعد أعلنته الشركة",
                    "source": e.get("source"), "source_url": e.get("source_url"), "announced_on": _day(e.get("date"))})
    return out


def federal_items(fr: Any, start: date, end: date) -> list[dict[str, Any]]:
    out = []
    for doc in (fr or {}).get("linked") or []:
        tickers = sorted({str(x.get("ticker")) for x in doc.get("links") or [] if x.get("ticker")})
        for field, kind, label in (("effective_on", "RULE_EFFECTIVE", "يسري مفعول وثيقة رسمية"),
                                   ("comments_close_on", "COMMENTS_CLOSE", "آخر موعد للتعليق على وثيقة رسمية")):
            when = _day(doc.get(field))
            if when and start.isoformat() <= when <= end.isoformat() and tickers:
                out.append({"date": when, "kind": kind, "symbols": tickers, "basis": f"FEDERAL_REGISTER_{field.upper()}",
                            "title": str(doc.get("title") or "")[:200], "title_ar": f"{label}: {doc.get('label_ar') or ''}".strip(),
                            "source": "Federal Register", "source_url": doc.get("source_url"),
                            "potential_impact": doc.get("potential_impact") or "NEEDS_IMPACT_ASSESSMENT"})
    return out


def build(catalysts: Any, fr: Any, now: datetime) -> dict[str, Any]:
    start = pd.Timestamp(now).tz_convert(NY).date()
    end = start + timedelta(days=DAYS)
    items = exchange_items(start, end) + company_items(catalysts, start, end) + federal_items(fr, start, end)
    items.sort(key=lambda x: (x["date"], x["kind"]))
    by_basis: dict[str, int] = {}
    for x in items:
        by_basis[x["basis"]] = by_basis.get(x["basis"], 0) + 1
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "window": {"from": start.isoformat(), "to": end.isoformat(),
            "timezone": NY}, "items": items, "counts": {"items": len(items), "by_basis": by_basis},
            "policy_ar": "مواعيد من مصادرها فقط: تقويم بورصة نيويورك، ومواعيد أعلنتها الشركات، وتواريخ تحددها وثائق Federal Register. "
                         "لا تقدير لمواعيد غير معلنة، والموعد لا يعني اتجاهًا للسعر.",
            "research_only": True, "decision_authority": False, "execution_authority": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalysts", type=Path)
    parser.add_argument("--federal-register", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(_load(args.catalysts), _load(args.federal_register), datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
