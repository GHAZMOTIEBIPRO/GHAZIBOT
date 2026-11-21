"""Dashboard and research center built from the published research artifacts.

Read-only. Each artifact passes the repository's publication guard first, then
the commercial rights gate in `rights.py`. What is withheld is counted and
explained, never silently dropped, and no price of unknown provenance is shown.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import rights
from .config import Config

STALE_HOURS = 36


def _read(cfg: Config, name: str, kind: str = "generic") -> tuple[dict[str, Any] | None, str | None]:
    path = Path(cfg.public_data_dir) / name
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "الملف غير موجود"
    except (OSError, ValueError):
        return None, "الملف تالف أو غير قابل للقراءة"
    if not isinstance(payload, dict):
        return None, "صيغة غير متوقعة"
    return rights.guarded(payload, kind=kind), None


def _age_hours(stamp: Any, now: datetime) -> float | None:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None  # a naive time cannot be aged honestly
    return round((now - dt).total_seconds() / 3600, 1)


def _freshness(stamp: Any, now: datetime) -> dict[str, Any]:
    age = _age_hours(stamp, now)
    return {"generated_at": stamp, "age_hours": age,
            "state": "UNKNOWN" if age is None else ("STALE" if age > STALE_HOURS else "RECENT"),
            "note_ar": "وقت إنتاج الملف لدينا، وليس وقت سعر من المزوّد."}


def dashboard(cfg: Config, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    health, health_err = _read(cfg, "health.json")
    status, _status_err = _read(cfg, "data-status.json")
    latest, latest_err = _read(cfg, "latest.json", kind="latest")
    index, index_err = _read(cfg, "index_radar.json")
    spx, spx_err = _read(cfg, "spx_dashboard.json")
    brief, brief_err = _read(cfg, "decision_brief.json")

    pipeline = {
        "status": (health or {}).get("status", "unknown"),
        "research_status": (health or {}).get("research_status"),
        "checks": (health or {}).get("checks") or {},
        "freshness": _freshness((health or {}).get("generated_at"), now),
        "error_ar": health_err,
    }
    if status:
        pipeline["active_stock_sources"] = (status.get("source_status") or {}).get("active_stock_sources")
        pipeline["active_option_sources"] = (status.get("source_status") or {}).get("active_option_sources")
        pipeline["reasons"] = (status.get("reasons") or [])[:6]

    sections = []
    for key, title_ar, payload, err in (("index", "المؤشرات (SPX/NDX/SPY/QQQ)", index, index_err),
                                        ("spx", "لوحة SPX", spx, spx_err)):
        payload = payload or {}
        st = payload.get("status") or ("MISSING" if err else "UNKNOWN")
        sections.append({"key": key, "title_ar": title_ar, "state": "AVAILABLE" if st == "OK" else "NOT_AVAILABLE",
                         "status": st, "reason_ar": payload.get("reason_ar") or err,
                         "enable_with": payload.get("enable_with"),
                         "freshness": _freshness(payload.get("generated_at"), now)})

    guard = (latest or {}).get("public_license_guard") or {}
    price_rows = len((brief or {}).get("stocks") or [])
    sections.append({
        "key": "prices", "title_ar": "أسعار الأسهم والعقود", "state": "NOT_AVAILABLE",
        "status": "NO_COMMERCIAL_PRICE_RIGHTS",
        "reason_ar": ("لا يوجد مصدر أسعار بحق عرض تجاري موثق في مصفوفة الحقوق؛ "
                      f"حُجب {price_rows} صف أسعار بحثي مصدره غير محدد. "
                      "الأسعار تُعرض فقط من بيانات يرفعها المستخدم لنفسه."),
        "closed_families": guard.get("closed_families"),
        "freshness": _freshness((brief or {}).get("generated_at"), now),
        "error_ar": latest_err or brief_err,
    })
    return {"schema": "ghazi.platform.dashboard.v1", "built_at": now.isoformat(timespec="seconds"),
            "pipeline": pipeline, "sections": sections,
            "authority": {"execution": False, "probability": None,
                          "note_ar": "منصة بحث ومعلومات؛ لا أوامر تداول ولا احتمالات نجاح ولا توصية مخصصة."}}


def research_center(cfg: Config, *, symbols: list[str] | None = None,
                    now: datetime | None = None) -> dict[str, Any]:
    """Catalyst and news items, each passed through the commercial rights gate."""
    now = now or datetime.now(timezone.utc)
    brief, brief_err = _read(cfg, "decision_brief.json")
    latest, latest_err = _read(cfg, "latest.json", kind="latest")
    raw: list[dict[str, Any]] = []
    for payload in (brief or {}, latest or {}):
        for item in payload.get("catalysts") or []:
            if isinstance(item, dict):
                raw.append(item)
    wanted = {s.upper() for s in symbols} if symbols else None
    items, withheld_text, dropped = [], 0, 0
    seen: set[tuple] = set()
    for item in raw:
        symbol = str(item.get("symbol") or "").upper()
        if wanted is not None and symbol not in wanted:
            continue
        link = rights.official_link(item.get("source_url") or item.get("url"))
        date = str(item.get("published_at") or item.get("date") or "")[:25] or None
        key = (symbol, link, date)
        if key in seen:
            continue
        seen.add(key)
        if not link or not date:
            dropped += 1  # without an official link and a publication date there is nothing verifiable to show
            continue
        source = item.get("source") or item.get("source_tier_reported")
        provider = rights.provider_for(source) or rights.provider_for(link)
        decision = rights.commercial_display(provider, derived=False, rights_path=cfg.source_rights_path)
        entry = {"symbol": symbol, "published_at": date, "source": source, "url": link,
                 "status": item.get("status"), "rights": decision,
                 "impact_note_ar": "أثر محتمل يحتاج تحققًا؛ ليس رد فعل سعريًا مثبتًا."}
        if decision["allowed"]:
            entry["title"] = item.get("headline") or item.get("title")
            entry["mode"] = "FULL"
        else:
            entry["title"] = None
            entry["mode"] = "LINK_ONLY"
            withheld_text += 1
        items.append(entry)
    items.sort(key=lambda e: e["published_at"] or "", reverse=True)
    return {"schema": "ghazi.platform.research.v1", "built_at": now.isoformat(timespec="seconds"),
            "items": items[:200], "total": len(items), "withheld_text": withheld_text,
            "dropped_unverifiable": dropped,
            "freshness": _freshness((brief or {}).get("generated_at"), now),
            "errors_ar": [e for e in (brief_err, latest_err) if e],
            "note_ar": ("يُعرض نص الخبر فقط حين يكون حق العرض التجاري لمصدره موثقًا؛ "
                        "غير ذلك يظهر الرابط الرسمي والتاريخ فقط لتقرأه من مصدره.")}
