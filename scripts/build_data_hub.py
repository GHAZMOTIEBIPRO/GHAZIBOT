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
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.data_hub.v1"


RIGHTS_KEYS = ("automated_access", "internal_analysis", "persistent_storage", "public_display_raw",
               "public_display_derived", "github_actions_automation", "commercial_use_on_free_tier",
               "telegram_sharing")
# Which providers can feed each engine. The class of each provider comes
# from its recorded rights only; a configured key never changes it.
ENGINE_PROVIDERS = {
    "PRICE": ("twelve_data", "tiingo", "finnhub", "alpaca", "alpha_vantage", "eodhd", "massive_polygon", "iex",
              "yahoo", "nasdaq_web", "tradingview_widgets"),
    "VOLUME": ("twelve_data", "tiingo", "finnhub", "alpaca", "alpha_vantage", "eodhd", "massive_polygon", "iex",
               "yahoo", "nasdaq_web"),
    "NEWS": ("gdelt", "federal_reserve", "sec_edgar", "google_news_rss", "prnewswire", "globenewswire",
             "businesswire"),
    "FUNDAMENTAL": ("sec_edgar", "fmp", "finnhub", "alpha_vantage", "eodhd", "nasdaq_data_link"),
    "OPTIONS": ("tradier", "massive_polygon", "alpaca", "marketdata_app", "cboe_delayed", "occ", "finnhub"),
    "MACRO": ("treasury_fiscaldata", "cftc", "federal_reserve", "bea", "census", "fred", "bls"),
    "REGULATORY": ("openfda", "sec_edgar"),
}


def provider_class(key: str, rights: dict[str, str]) -> str:
    """PUBLIC / DISPLAY_WIDGET_ONLY / INTERNAL_ONLY / BLOCKED / UNKNOWN from recorded rights."""
    if key == "tradingview_widgets":
        return "DISPLAY_WIDGET_ONLY"
    if rights.get("automated_access") == "RESTRICTED":
        return "BLOCKED"
    if "VERIFIED" in (rights.get("public_display_raw"), rights.get("public_display_derived")):
        return "PUBLIC"
    if rights.get("automated_access") == "VERIFIED" and rights.get("internal_analysis") == "VERIFIED":
        return "INTERNAL_ONLY"
    if rights.get("internal_analysis") == "RESTRICTED":
        return "BLOCKED"
    return "UNKNOWN"


def provider_engines(providers: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for engine, keys in ENGINE_PROVIDERS.items():
        classes = {k: provider_class(k, providers[k]["rights"]) for k in keys if k in providers}
        public = sorted(k for k, c in classes.items() if c == "PUBLIC")
        internal = sorted(k for k, c in classes.items() if c == "INTERNAL_ONLY")
        out[engine] = {
            "providers": classes,
            "public_sources": public,
            "internal_only_sources": internal,
            "status": ("PUBLIC_SOURCE_AVAILABLE" if public else
                       "INTERNAL_ONLY_WITH_KEY" if internal else
                       "DISPLAY_WIDGET_ONLY" if "DISPLAY_WIDGET_ONLY" in classes.values() else "NO_PERMITTED_SOURCE"),
        }
    return out


def _source_rights() -> dict[str, Any]:
    """Compact public view of data/source_rights.json (official-terms evidence)."""
    path = Path(__file__).resolve().parents[1] / "data" / "source_rights.json"
    try:
        matrix = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False}
    providers = {}
    for key, entry in (matrix.get("providers") or {}).items():
        rights = entry.get("rights") or {}
        providers[key] = {
            "name": entry.get("name"), "category": entry.get("category"),
            "official_url": entry.get("official_url"), "summary_ar": entry.get("summary_ar"),
            "rights": {r: (rights.get(r) or {}).get("status", "UNKNOWN") for r in RIGHTS_KEYS},
        }
    return {"available": True, "checked_at": matrix.get("checked_at"), "evidence_run": matrix.get("evidence_run"),
            "full_text_run": matrix.get("full_text_run"), "unknown_is_not_permission": True,
            "providers": providers, "engines": provider_engines(providers)}


def _source_gates() -> dict[str, Any]:
    # Loaded by path: the package __init__ needs pandas, this job has none.
    path = Path(__file__).resolve().parents[1] / "options_radar" / "source_permissions.py"
    spec = importlib.util.spec_from_file_location("ghazi_source_permissions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gate_status()

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
     "source": "Yahoo (yfinance)", "license_class": "TERMS_RESTRICTED", "cadence_min": 30,
     "limitations": "شموع غير رسمية وقد تتأخر؛ ليست أسعار تنفيذ"},
    {"file": "index_charts.json", "title_ar": "شارتات المؤشرات", "kind": "OHLC_BARS",
     "source": "Yahoo (yfinance)", "license_class": "TERMS_RESTRICTED", "cadence_min": 30,
     "limitations": "شموع غير رسمية وقد تتأخر"},
    {"file": "stock_watch_charts.json", "title_ar": "شارتات الأسهم", "kind": "OHLC_BARS",
     "source": "Yahoo (yfinance)", "license_class": "TERMS_RESTRICTED", "cadence_min": 60,
     "limitations": "شموع غير رسمية وقد تتأخر"},
    {"file": "liquidity_map.json", "title_ar": "الحجم والسيولة", "kind": "DERIVED_ANALYTICS",
     "source": "مشتق من شموع Yahoo 15 دقيقة", "license_class": "TERMS_RESTRICTED", "cadence_min": 60,
     "limitations": "استنتاج من الشموع؛ لا دفتر أوامر"},
    {"file": "classical_direction.json", "title_ar": "الاتجاه الكلاسيكي للأسهم", "kind": "DIRECTION",
     "source": "مشتق من شموع Yahoo للأسهم", "license_class": "TERMS_RESTRICTED", "cadence_min": 60,
     "limitations": "اتجاه بحثي؛ ليس احتمال نجاح"},
    {"file": "decision_brief.json", "title_ar": "ملخص الترشيحات", "kind": "DIRECTION",
     "source": "رادار الأسهم", "license_class": "DERIVED_PUBLIC", "cadence_min": 60,
     "limitations": "ترتيب بحثي"},
    {"file": "explosion_hunter.json", "title_ar": "رادار الانفجار", "kind": "SCREENER",
     "source": "Nasdaq screener + Yahoo", "license_class": "TERMS_RESTRICTED", "cadence_min": 45,
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
     "source": "OCC + FilingPulse", "license_class": "TERMS_RESTRICTED", "cadence_min": 360,
     "limitations": "شروط OCC تمنع الوصول الآلي؛ التقارير متوقفة حتى ترخيص OCC"},
    {"file": "free_public_intelligence.json", "title_ar": "الأخبار والاقتصاد", "kind": "NEWS",
     "source": "Google News RSS + Fed + BLS", "license_class": "MIXED_HEADLINES_AND_OFFICIAL", "cadence_min": 60,
     "limitations": "العناوين لا تثبت اتجاه الأثر"},
    {"file": "public_macro.json", "title_ar": "تموضع عقود المؤشرات وعائدات الخزانة", "kind": "MACRO_CONTEXT",
     "source": "CFTC TFF + U.S. Treasury", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 720,
     "limitations": "مراكز CFTC أسبوعية (الثلاثاء)؛ العائدات يومية بعد 15:30 نيويورك؛ سياق لا إشارة"},
    {"file": "macro_regimes.json", "title_ar": "أنظمة منحنى العائد وتموضع العقود (ruptures)", "kind": "MACRO_CONTEXT",
     "source": "CFTC TFF + U.S. Treasury · ruptures", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 720,
     "limitations": "تقسيم وصفي لتاريخ السلاسل؛ لا يتنبأ بانكسار ولا يحدد اتجاهًا"},
    {"file": "fda_events.json", "title_ar": "أحداث FDA الرسمية", "kind": "REGULATORY_EVENTS",
     "source": "openFDA (CC0)", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 720,
     "limitations": "وقائع تنظيمية لا اتجاه سعر؛ openFDA يتأخر عن قرارات FDA أيامًا"},
    {"file": "catalyst_watchlist.json", "title_ar": "قائمة متابعة المحفزات الرسمية", "kind": "REGULATORY_EVENTS",
     "source": "openFDA (CC0) + SEC EDGAR", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 720,
     "limitations": "محفزات رسمية لا اتجاه سعر؛ لا تصنيف تحت 10$ دون سعر مسموح حديث"},
    {"file": "issuer_sizes.json", "title_ar": "حجم الشركات من SEC (Public Float)", "kind": "FILINGS",
     "source": "SEC XBRL dei:EntityPublicFloat", "license_class": "OFFICIAL_PUBLIC", "cadence_min": 1440,
     "limitations": "قيمة الأسهم الحرة لغير المطلعين سنويًا من 10-K؛ ليست قيمة سوقية؛ يحتاج SEC_USER_AGENT"},
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
    {"file": "platform_scorecards.json", "title_ar": "مقاييس المنصة المستقلة", "kind": "EVALUATION",
     "source": "سجل التشغيل + الملفات المنشورة", "license_class": "INTERNAL_METRIC", "cadence_min": 360,
     "limitations": "مقاييس منفصلة بلا رقم مجمّع؛ غير المقاس يظهر UNMEASURED"},
    {"file": "site_smoke.json", "title_ar": "فحص الموقع بالمتصفح", "kind": "OPERATIONS",
     "source": "متصفح آلي على الموقع المنشور", "license_class": "INTERNAL_METRIC", "cadence_min": 360,
     "limitations": "يقيس سلامة العرض لا صحة البيانات"},
    {"file": "live_dashboard_status.json", "title_ar": "حالة المحركات", "kind": "OPERATIONS",
     "source": "سجل التشغيل", "license_class": "INTERNAL_METRIC", "cadence_min": 30,
     "limitations": "تشغيل وليس جودة إشارة"},
]

# One public state per dataset, from the recovery directive's taxonomy.
# LIVE is listed for completeness: nothing here carries a licensed live
# quote, so no dataset can reach it. Order of the rules is fail-closed:
# absence, failed validation, licence and timing beat what the data is.
DATA_STATES = {
    "LIVE": "حي من مصدر مرخص",
    "DELAYED": "رسمي منشور بتأخر معروف",
    "HISTORICAL": "نتائج تاريخية مكتملة",
    "STALE": "قديم أو بلا وقت موثق",
    "LICENSE_BLOCKED": "محجوب حتى الترخيص",
    "SOURCE_UNAVAILABLE": "المصدر لم يستجب",
    "MODEL_ESTIMATED": "تقدير نموذجي",
    "RESEARCH_ONLY": "بحثي/تشغيلي فقط",
    "VALIDATION_FAILED": "فشل التحقق",
    "DATA_UNAVAILABLE": "غير منشور",
}
_MODEL_KINDS = {"OPTIONS_MODEL", "OPTIONS_DERIVED", "DERIVED_ANALYTICS"}
_DELAYED_KINDS = {"MACRO_CONTEXT", "REGULATORY_EVENTS", "FILINGS", "NEWS", "OPTIONS_CONTEXT"}
_HISTORICAL_FILES = {"explosion_stage_evaluation.json", "stock_audit_public.json"}


def data_state(row: dict[str, Any], payload: Any) -> str:
    if not row.get("present"):
        return "DATA_UNAVAILABLE"
    if row.get("validation") == "FAIL":
        return "VALIDATION_FAILED"
    if row.get("rights_status") in {"BLOCKED_PENDING_PERMISSION", "RESTRICTED", "NOT_AUTHORISED_FALLBACK"}:
        return "LICENSE_BLOCKED"
    status = str(payload.get("status") or "").upper() if isinstance(payload, dict) else ""
    if status in {"SOURCE_UNAVAILABLE", "UNAVAILABLE", "BLOCKED_BY_SOURCE"}:
        return "SOURCE_UNAVAILABLE"
    if row.get("freshness") != "FRESH":
        return "STALE"
    if row["kind"] in _MODEL_KINDS:
        return "MODEL_ESTIMATED"
    if row["file"] in _HISTORICAL_FILES:
        return "HISTORICAL"
    if row["license_class"] == "OFFICIAL_PUBLIC" or row["kind"] in _DELAYED_KINDS:
        return "DELAYED"
    return "RESEARCH_ONLY"


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
        row["data_state"] = data_state(row, payload)
        row["data_state_ar"] = DATA_STATES[row["data_state"]]
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["freshness"]] = counts.get(row["freshness"], 0) + 1
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "datasets": rows,
        "source_gates": _source_gates(),
        "source_rights": _source_rights(),
        "data_states": DATA_STATES,
        "summary": {"total": len(rows), "freshness": counts,
                    "data_states": {k: sum(r["data_state"] == k for r in rows)
                                    for k in DATA_STATES if any(r["data_state"] == k for r in rows)},
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
