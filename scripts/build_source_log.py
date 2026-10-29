"""Operational log per data source: what it is, and how its real fetches went.

For each source:
- what it supplies, its coverage, delay, whether it needs a key, and which uses its
  recorded rights allow (data/source_rights.json);
- from the bot-state history of the file its producer writes (one version per run
  that published), over WINDOW_DAYS: attempts, successes, the last successful fetch
  and the success ratio.

A run that a gate or a missing key stopped is NOT_ATTEMPTED, never a failure. A run
that crashed before writing its file leaves no version, so it is not counted here:
workflow run health is a separate measure (platform_scorecards.json "reliability").
Standard library only; reads git and files, makes no network request.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.source_log.v1"
WINDOW_DAYS = 14
ROOT = Path(__file__).resolve().parents[1]
DATA = "runtime/public/data/"
RIGHT_USES = {"internal_analysis": "تحليل داخلي", "persistent_storage": "تخزين", "public_display_raw": "عرض البيانات الخام",
              "public_display_derived": "عرض النتائج المشتقة", "telegram_sharing": "مشاركة في تيليجرام"}
SKIPPED = {"DATA_USE_PERMISSION_REQUIRED", "ACCOUNT_CREDENTIALS_NOT_CONFIGURED", "SOURCE_TERMS_BLOCKED",
           "SEC_IDENTITY_MISSING", "NO_API_KEY_HEALTH_ONLY", "ACCOUNT_ENTITLEMENT_NOT_ASSERTED", "NOT_CONFIGURED"}


def _alpaca(d: dict[str, Any]) -> tuple[str, str]:
    mode = d.get("private_mode") or {}
    reason = str(mode.get("reason") or "UNKNOWN")
    if not mode.get("enabled"):
        return "NOT_ATTEMPTED", reason
    fetched = ((d.get("analysis_funnel") or {}).get("bars_fetched") or {})
    ok, tried = fetched.get("count") or 0, fetched.get("attempted") or 0
    return ("OK" if tried and ok == tried else "PARTIAL" if ok else "FAILED"), f"{ok}/{tried} symbols with daily bars"


def _status_field(ok: tuple[str, ...] = ("OK", "AVAILABLE"), partial: tuple[str, ...] = ("PARTIAL", "DEGRADED")
                  ) -> Callable[[dict[str, Any]], tuple[str, str]]:
    def read(d: dict[str, Any]) -> tuple[str, str]:
        s = str(d.get("status") or "UNKNOWN")
        return ("OK" if s in ok else "PARTIAL" if s in partial else "NOT_ATTEMPTED" if s in SKIPPED else "FAILED"), s
    return read


def _counts(ok_key: str, all_key: str) -> Callable[[dict[str, Any]], tuple[str, str]]:
    def read(d: dict[str, Any]) -> tuple[str, str]:
        c = d.get("counts") or {}
        ok, total = c.get(ok_key), c.get(all_key)
        if not isinstance(ok, int) or not isinstance(total, int) or not total:
            return "FAILED", "no counts"
        return ("OK" if ok == total else "PARTIAL" if ok else "FAILED"), f"{ok}/{total}"
    return read


def _errors_empty(d: dict[str, Any]) -> tuple[str, str]:
    errs = d.get("errors")
    return ("OK", "no errors") if errs == {} else ("PARTIAL", ",".join(sorted(errs))[:80]) if isinstance(errs, dict) \
        else ("FAILED", "no error record")


def _treasury(d: dict[str, Any]) -> tuple[str, str]:
    t = d.get("treasury_curve") or {}
    return ("OK", f"curve {t.get('curve_date')}") if t.get("available") else ("FAILED", "curve unavailable")


def _cftc(d: dict[str, Any]) -> tuple[str, str]:
    rows = [v for v in (d.get("cftc_index_futures") or {}).values() if isinstance(v, dict)]
    ok = [v for v in rows if v.get("available")]
    if not rows:
        return "FAILED", "no markets"
    return ("OK" if len(ok) == len(rows) else "PARTIAL" if ok else "FAILED"), \
        f"{len(ok)}/{len(rows)} markets, positions {max((v.get('positions_as_of') or '') for v in ok) if ok else '-'}"


def _liquidity(block: str, date_field: str) -> Any:
    def read(d: dict[str, Any]) -> tuple[str, str]:
        b = d.get(block) or {}
        if not b.get("available"):
            return "FAILED", str(b.get("reason") or "unavailable")[:80]
        if b.get("kept_previous_copy"):
            return "FAILED", f"kept previous copy: {str(b.get('kept_reason'))[:60]}"
        value = b.get(date_field) or (b.get("sofr") or {}).get("date") or (b.get("tri_party_rate") or {}).get("date")
        return ("PARTIAL" if b.get("stale") else "OK"), f"as of {value}"
    return read


def _federal_register(d: dict[str, Any]) -> tuple[str, str]:
    c = d.get("counts") or {}
    return ("OK", f"{c.get('after_noise_filter')} documents") if isinstance(c.get("after_noise_filter"), int) \
        else ("FAILED", "no counts")


def _tradier(d: dict[str, Any]) -> tuple[str, str]:
    s = str((d.get("tradier") or {}).get("status") or "UNKNOWN")
    return ("NOT_ATTEMPTED" if s in SKIPPED else "OK" if s == "OK" else "FAILED"), s


# priority follows the assignment: candles, then options, then SEC, IR, government, optional FRED
SOURCES: list[dict[str, Any]] = [
    {"key": "alpaca_bars", "rights": "alpaca", "priority": 1, "name_ar": "شموع Alpaca (IEX/SIP)",
     "data_type": "شموع أسعار الأسهم والصناديق (يومي و5 دقائق، تُبنى منها 15د/1س/4س)",
     "coverage": "الأسهم الأمريكية والصناديق المتداولة", "delay": "شموع مكتملة فقط؛ لا شيء من آخر 16 دقيقة",
     "key_required": "ALPACA_API_KEY, ALPACA_SECRET_KEY + ALPACA_INTERNAL_DATA_USE_AUTHORIZED",
     "file": "daily_plan.json", "read": _alpaca},
    {"key": "tradier_options", "rights": "tradier", "priority": 2, "name_ar": "سلاسل خيارات Tradier",
     "data_type": "سلاسل خيارات واقتباسات", "coverage": "خيارات الأسهم الأمريكية (حساب Tradier)",
     "delay": "بيئة الاختبار متأخرة 15 دقيقة", "key_required": "حساب Tradier ورمز وصول",
     "file": "free_options_sources.json", "read": _tradier},
    {"key": "cboe_delayed", "rights": "cboe_delayed", "priority": 2, "name_ar": "اقتباسات Cboe المتأخرة",
     "data_type": "اقتباسات خيارات متأخرة", "coverage": "خيارات مدرجة", "delay": "15 دقيقة", "key_required": "لا",
     "file": "options_analytics.json", "read": _status_field()},
    {"key": "sec_edgar", "rights": "sec_edgar", "priority": 3, "name_ar": "SEC EDGAR",
     "data_type": "الإفصاحات والقوائم المالية (XBRL)", "coverage": "الشركات المسجلة لدى SEC",
     "delay": "دقائق من الإيداع", "key_required": "هوية SEC_USER_AGENT (ليست مفتاحًا)",
     "file": "sec_filing_pulse.json", "read": _status_field()},
    {"key": "company_ir_feeds", "rights": "company_ir_feeds", "priority": 4, "name_ar": "خلاصات علاقات المستثمرين الرسمية",
     "data_type": "بيانات الشركات ومواعيد النتائج", "coverage": "الشركات في data/ir_feeds.json",
     "delay": "عند نشر الشركة", "key_required": "لا", "file": "ir_news.json", "read": _counts("sources_ok", "sources")},
    {"key": "treasury", "rights": "treasury_fiscaldata", "priority": 5, "name_ar": "منحنى عوائد الخزانة",
     "data_type": "عوائد السندات اليومية", "coverage": "منحنى العائد الاسمي", "delay": "يوم عمل",
     "key_required": "لا", "file": "public_macro.json", "read": _treasury},
    {"key": "cftc", "rights": "cftc", "priority": 5, "name_ar": "تقارير CFTC للمراكز",
     "data_type": "مراكز العقود الآجلة الأسبوعية", "coverage": "عقود مؤشرات مختارة", "delay": "أسبوعي (مراكز الثلاثاء)",
     "key_required": "لا", "file": "public_macro.json", "read": _cftc},
    {"key": "dol_claims", "rights": "dol_eta539", "priority": 5, "name_ar": "طلبات إعانة البطالة (وزارة العمل)",
     "data_type": "طلبات الإعانة الأسبوعية حسب الولاية (غير معدّلة موسميًا)", "coverage": "الولايات الأمريكية",
     "delay": "نحو 11 يومًا بعد نهاية الأسبوع", "key_required": "لا",
     "file": "liquidity_monitor.json", "read": _liquidity("claims", "week_ending")},
    {"key": "nyfed_rates", "rights": "nyfed_reference_rates", "priority": 5, "name_ar": "فوائد الاحتياطي الفيدرالي في نيويورك",
     "data_type": "SOFR وEFFR والنطاق المستهدف", "coverage": "أسواق التمويل لليلة واحدة",
     "delay": "يوم العمل التالي نحو 08:00 بتوقيت نيويورك", "key_required": "لا",
     "file": "liquidity_monitor.json", "read": _liquidity("funding_rates", "")},
    {"key": "ofr_repo", "rights": "ofr_stfm", "priority": 5, "name_ar": "مراقب التمويل قصير الأجل (OFR)",
     "data_type": "فائدة وحجم الريبو الثلاثي، واستثمار صناديق النقد في الريبو", "coverage": "سوق الريبو الأمريكية",
     "delay": "يومي أولي (الريبو) وشهري معدّل (الصناديق)", "key_required": "لا",
     "file": "liquidity_monitor.json", "read": _liquidity("repo", "")},
    {"key": "usaspending", "rights": "usaspending", "priority": 5, "name_ar": "عقود USAspending الحكومية",
     "data_type": "إجراءات العقود الفيدرالية", "coverage": "الشركات في data/usaspending_recipients.json",
     "delay": "تأخر نشر الجهات (الدفاع نحو 90 يومًا)", "key_required": "لا",
     "file": "usaspending_contracts.json", "read": _counts("companies_ok", "companies")},
    {"key": "openfda", "rights": "openfda", "priority": 5, "name_ar": "openFDA", "data_type": "موافقات الأدوية والاستدعاءات",
     "coverage": "FDA", "delay": "تحديث مجموعة البيانات (أسبوعي تقريبًا)", "key_required": "لا",
     "file": "fda_events.json", "read": _errors_empty},
    {"key": "clinicaltrials", "rights": None, "priority": 5, "name_ar": "ClinicalTrials.gov",
     "data_type": "سجل الدراسات السريرية", "coverage": "دراسات مرتبطة بالجهات المراجعة", "delay": "عند تحديث السجل",
     "key_required": "لا", "file": "clinical_registry.json", "read": _status_field()},
    {"key": "federal_register", "rights": "federal_register", "priority": 5, "name_ar": "السجل الفيدرالي",
     "data_type": "إشعارات الجهات التنظيمية", "coverage": "وثائق الجهات المختارة", "delay": "يوم النشر",
     "key_required": "لا", "file": "federal_register.json", "read": _federal_register},
    {"key": "fred", "rights": "fred", "priority": 6, "name_ar": "FRED (اختياري)", "data_type": "سلاسل اقتصادية",
     "coverage": "اقتصاد أمريكي", "delay": "حسب السلسلة", "key_required": "FRED_API_KEY + FRED_AUTOMATION_APPROVED",
     "file": None, "read": None},
    {"key": "yahoo", "rights": "yahoo", "priority": 9, "name_ar": "Yahoo (موقوف)", "data_type": "أسعار ومؤشرات",
     "coverage": "واسعة", "delay": "متأخرة", "key_required": "لا (الشروط تمنع الجلب الآلي)",
     "file": "index_radar.json", "read": _status_field()},
]


def versions(repo: Path, path: str, since: datetime, rev: str = "HEAD") -> list[tuple[str, str]]:
    """(commit, file text) for each version of `path` committed since `since`, oldest first."""
    log = subprocess.run(["git", "-C", str(repo), "log", rev, "--reverse", f"--since={since.isoformat()}",
                          "--format=%H", "--", path], capture_output=True, text=True, timeout=120, check=False)
    out = []
    for sha in log.stdout.split():
        show = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{path}"], capture_output=True, text=True,
                              timeout=120, check=False)
        if show.returncode == 0:
            out.append((sha, show.stdout))
    return out


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def history(source: dict[str, Any], texts: list[tuple[str, str]], since: datetime) -> dict[str, Any]:
    """Outcomes of the source's runs (one per distinct generated_at) inside the window."""
    seen: dict[str, tuple[str, str, str]] = {}
    for sha, text in texts:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        stamp = _parse(data.get("generated_at")) if isinstance(data, dict) else None
        if stamp is None or stamp < since:
            continue
        outcome, detail = source["read"](data)
        seen[stamp.isoformat()] = (outcome, detail, sha)
    runs = [(t, *v) for t, v in sorted(seen.items())]
    attempted = [r for r in runs if r[1] != "NOT_ATTEMPTED"]
    good = [r for r in attempted if r[1] in ("OK", "PARTIAL")]
    last_ok = good[-1] if good else None
    last = runs[-1] if runs else None
    return {"runs_seen": len(runs), "attempted": len(attempted), "succeeded": len(good),
            "fully_ok": sum(1 for r in attempted if r[1] == "OK"),
            "success_ratio": round(len(good) / len(attempted), 3) if attempted else None,
            "last_success_at": last_ok[0] if last_ok else None,
            "last_run_at": last[0] if last else None,
            "last_outcome": last[1] if last else "NO_RUN_RECORDED", "last_detail": last[2] if last else None,
            "last_commit": last[3][:10] if last else None}


def allowed_uses(rights: dict[str, Any] | None) -> dict[str, list[str]]:
    rows = (rights or {}).get("rights") or {}
    status = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in rows.items()}
    return {"verified": [RIGHT_USES[k] for k in RIGHT_USES if status.get(k) == "VERIFIED"],
            "restricted": [RIGHT_USES[k] for k in RIGHT_USES if status.get(k) == "RESTRICTED"],
            "unknown": [RIGHT_USES[k] for k in RIGHT_USES if status.get(k) not in ("VERIFIED", "RESTRICTED")]}


def build(repo: Path, now: datetime, rights: dict[str, Any], window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    since = now - timedelta(days=window_days)
    rows = []
    for src in SOURCES:
        h = (history(src, versions(repo, DATA + src["file"], since), since) if src["file"] else
             {"runs_seen": 0, "attempted": 0, "succeeded": 0, "fully_ok": 0, "success_ratio": None,
              "last_success_at": None, "last_run_at": None, "last_outcome": "NOT_CONFIGURED", "last_detail": None,
              "last_commit": None})
        rows.append({k: src[k] for k in ("key", "priority", "name_ar", "data_type", "coverage", "delay", "key_required",
                                          "file")}
                    | {"uses": allowed_uses((rights.get("providers") or {}).get(src["rights"])) if src["rights"] else
                       {"verified": [], "restricted": [], "unknown": list(RIGHT_USES.values())},
                       "rights_key": src["rights"]} | h)
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "window_days": window_days,
            "window_start": since.isoformat(),
            "method": ("One run = one published version of the producer's file (distinct generated_at) on bot-state. "
                       "NOT_ATTEMPTED (gate, key, terms) is excluded from the ratio; a run that never wrote its file "
                       "is not seen here (see workflow reliability)."),
            "method_ar": ("كل تشغيل = نسخة منشورة من ملف المصدر على bot-state خلال النافذة. التشغيل الموقوف بسبب شرط أو مفتاح "
                          "لا يُحسب فشلًا ولا نجاحًا. نجاح الجلب لا يعني صحة التحليل."),
            "sources": rows, "research_only": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True, help="bot-state checkout with history")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rights = json.loads((ROOT / "data" / "source_rights.json").read_text(encoding="utf-8"))
    report = build(args.repo, datetime.now(timezone.utc), rights)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps([(s["key"], s["last_outcome"], s["attempted"], s["success_ratio"]) for s in report["sources"]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
