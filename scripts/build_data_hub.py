"""GHAZI MARKET DATA HUB: one catalog of every published dataset.

Standard library only (runs in the dependency-free evidence workflow).
For each dataset it reports presence, the dataset's own timestamp (never
the hub's clock), age, freshness against the producer's expected cadence,
basic validation, the source family, the license class that decides how
the site may show it, and known limitations. It reads files; it makes no
network requests and changes no dataset.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.data_hub.v1"

# license_class:
#   DERIVED_PUBLIC     - only derived research values are published
#   FALLBACK_LABELLED  - source's automated-access terms are not satisfied;
#                        kept as a labelled research fallback until replaced
#   OFFICIAL_PUBLIC    - official public-sector or exchange-allowed source
#   INTERNAL_METRIC    - project's own audit/evaluation output
#   TERMS_RESTRICTED   - provider terms restrict automated use / publication;
#                        gated off until the owner records permission
#   MIXED_HEADLINES_AND_OFFICIAL - official releases plus search headlines
REGISTRY: list[dict[str, Any]] = [
    {"file": "index_radar.json", "title_ar": "رادار المؤشرات", "kind": "INDEX_DIRECTION",
     "source": "Yahoo (yfinance)", "license_class": "FALLBACK_LABELLED", "cadence_min": 30,
     "limitations": "شموع غير رسمية وقد تتأخر؛ ليست أسعار تنفيذ"},
    {"file": "index_charts.json", "title_ar": "شارتات المؤشرات", "kind": "OHLC_BARS",
     "source": "Yahoo (yfinance)", "license_class": "FALLBACK_LABELLED", "cadence_min": 30,
     "limitations": "شموع غير رسمية وقد تتأخر"},
    {"file": "stock_watch_charts.json", "title_ar": "شارتات الأسهم", "kind": "OHLC_BARS",
     "source": "Yahoo (yfinance)", "license_class": "FALLBACK_LABELLED", "cadence_min": 60,
     "limitations": "شموع غير رسمية وقد تتأخر"},
    {"file": "liquidity_map.json", "title_ar": "الحجم والسيولة", "kind": "DERIVED_ANALYTICS",
     "source": "مشتق من شموع 15 دقيقة", "license_class": "DERIVED_PUBLIC", "cadence_min": 60,
     "limitations": "استنتاج من الشموع؛ لا دفتر أوامر"},
    {"file": "classical_direction.json", "title_ar": "الاتجاه الكلاسيكي للأسهم", "kind": "DIRECTION",
     "source": "مشتق من شموع الأسهم", "license_class": "DERIVED_PUBLIC", "cadence_min": 60,
     "limitations": "اتجاه بحثي؛ ليس احتمال نجاح"},
    {"file": "decision_brief.json", "title_ar": "ملخص الترشيحات", "kind": "DIRECTION",
     "source": "رادار الأسهم", "license_class": "DERIVED_PUBLIC", "cadence_min": 60,
     "limitations": "ترتيب بحثي"},
    {"file": "explosion_hunter.json", "title_ar": "رادار الانفجار", "kind": "SCREENER",
     "source": "Nasdaq screener + Yahoo", "license_class": "FALLBACK_LABELLED", "cadence_min": 45,
     "limitations": "مصدر الاكتشاف غير مصرح للأتمتة؛ أداء المراحل تاريخيًا دون التعادل"},
    {"file": "explosion_stage_evaluation.json", "title_ar": "تقييم مراحل الانفجار", "kind": "EVALUATION",
     "source": "سجل النتائج المكتملة", "license_class": "INTERNAL_METRIC", "cadence_min": 1440,
     "limitations": "تكاليف التداول افتراضية"},
    {"file": "free_gex_validation.json", "title_ar": "جاما SPX", "kind": "OPTIONS_MODEL",
     "source": "Cboe delayed", "license_class": "TERMS_RESTRICTED", "cadence_min": 30,
     "limitations": "مستويات نموذجية وليست مراكز صناع السوق"},
    {"file": "options_analytics.json", "title_ar": "تحليلات العقود", "kind": "OPTIONS_DERIVED",
     "source": "Cboe delayed", "license_class": "TERMS_RESTRICTED", "cadence_min": 30,
     "limitations": "مؤجل وغير تنفيذي؛ قيم مشتقة فقط"},
    {"file": "free_options_sources.json", "title_ar": "مصادر الخيارات المجانية", "kind": "OPTIONS_CONTEXT",
     "source": "OCC + FilingPulse", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 360,
     "limitations": "OI غير لحظي"},
    {"file": "free_public_intelligence.json", "title_ar": "الأخبار والاقتصاد", "kind": "NEWS",
     "source": "Google News RSS + Fed + BLS", "license_class": "MIXED_HEADLINES_AND_OFFICIAL", "cadence_min": 60,
     "limitations": "العناوين لا تثبت اتجاه الأثر"},
    {"file": "sec_filing_pulse.json", "title_ar": "إفصاحات SEC", "kind": "FILINGS",
     "source": "SEC EDGAR", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 240,
     "limitations": "محجوب حتى إضافة SEC_USER_AGENT"},
    {"file": "source_agreement.json", "title_ar": "توافق مصادر الأسعار", "kind": "VALIDATION",
     "source": "مقارنة المصادر", "license_class": "INTERNAL_METRIC", "cadence_min": 60,
     "limitations": "يحتاج مصدرين مرخصين"},
    {"file": "stock_audit_public.json", "title_ar": "تدقيق نتائج الإشارات", "kind": "EVALUATION",
     "source": "سجل النتائج", "license_class": "INTERNAL_METRIC", "cadence_min": 1440,
     "limitations": "ليس نسبة نجاح تنفيذية"},
    {"file": "site_strength.json", "title_ar": "درجة الموثوقية", "kind": "EVALUATION",
     "source": "تدقيق الأدلة", "license_class": "INTERNAL_METRIC", "cadence_min": 360,
     "limitations": "جاهزية بيانات وليست دقة تنبؤ"},
    {"file": "live_dashboard_status.json", "title_ar": "حالة المحركات", "kind": "OPERATIONS",
     "source": "سجل التشغيل", "license_class": "INTERNAL_METRIC", "cadence_min": 30,
     "limitations": "تشغيل وليس جودة إشارة"},
]

# Fields that, when present, must hold these values for the file to pass.
GUARDS = {"decision_authority": False, "execution_authority": False, "execution_grade": False,
          "quote_execution_eligible": False, "score_is_probability": False}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _regular_hours(now: datetime) -> bool:
    """Approximate U.S. regular session window in UTC (13:30-21:00 covers
    both EDT and EST); weekends excluded. Only used to pick a tolerance."""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= minutes <= 21 * 60


def assess(entry: dict[str, Any], payload: Any, now: datetime) -> dict[str, Any]:
    out = {k: entry[k] for k in ("file", "title_ar", "kind", "source", "license_class", "cadence_min", "limitations")}
    if payload is None:
        return {**out, "present": False, "freshness": "MISSING", "validation": "MISSING",
                "rights_status": "UNKNOWN",
                "generated_at": None, "age_minutes": None}
    stamp_raw = payload.get("generated_at") or payload.get("updated_at") if isinstance(payload, dict) else None
    stamp = _parse(stamp_raw)
    age = round((now - stamp).total_seconds() / 60, 1) if stamp else None
    if age is None:
        freshness = "UNTIMED"
    elif age < -5:
        freshness = "FUTURE_TIMESTAMP"
    else:
        factor = 3 * entry["cadence_min"]
        tolerance = factor if _regular_hours(now) else max(factor, 72 * 60 if now.weekday() >= 5 else 18 * 60)
        freshness = "FRESH" if age <= tolerance else "STALE"
    problems = []
    if isinstance(payload, dict):
        for key, expected in GUARDS.items():
            if key in payload and payload[key] is not expected:
                problems.append(f"{key}!={expected}")
    else:
        problems.append("not_an_object")
    blocked = isinstance(payload, dict) and (
        payload.get("status") == "SOURCE_TERMS_BLOCKED"
        or (payload.get("integrated_engines", {}).get("ghazi_gex_multi", {}) or {}).get("status")
        == "SOURCE_TERMS_BLOCKED")
    out["rights_status"] = ("BLOCKED_PENDING_PERMISSION" if blocked else
                            {"TERMS_RESTRICTED": "RESTRICTED", "FALLBACK_LABELLED": "NOT_AUTHORISED_FALLBACK"}
                            .get(entry["license_class"], "OK_FOR_STATED_USE"))
    return {**out, "present": True, "generated_at": stamp.isoformat() if stamp else None,
            "age_minutes": age, "freshness": freshness,
            "validation": "PASS" if not problems else "FAIL", "validation_problems": problems,
            "schema": payload.get("schema") if isinstance(payload, dict) else None}


def build(data_dir: Path, now: datetime) -> dict[str, Any]:
    rows = []
    for entry in REGISTRY:
        path = data_dir / entry["file"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, ValueError):
            payload = {"_unreadable": True}
        row = assess(entry, payload, now)
        if isinstance(payload, dict) and payload.get("_unreadable"):
            row.update(validation="FAIL", validation_problems=["unreadable_json"], freshness="UNTIMED")
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["freshness"]] = counts.get(row["freshness"], 0) + 1
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "datasets": rows,
        "summary": {"total": len(rows), "freshness": counts,
                    "rights": {k: sum(r.get("rights_status") == k for r in rows)
                               for k in sorted({r.get("rights_status") for r in rows})},
                    "validation_failures": sum(r["validation"] == "FAIL" for r in rows),
                    "fallback_sources": sorted({r["source"] for r in rows
                                                if r["license_class"] == "FALLBACK_LABELLED"})},
        "policy": {"timestamps_are_dataset_own": True, "network_requests": False,
                   "freshness_is_not_quote_time": True,
                   "freshness_is_not_correctness_or_licence": True},
        "research_only": True,
        "decision_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build(Path(args.data_dir), datetime.now(timezone.utc))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Data hub:", json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
