"""Independent platform scorecards, kept apart from the evidence score.

The research-readiness score (site_strength.json) keeps its weights and
history. This report measures seven separate things, each from its own
evidence, and never folds them into one number:

1. SYSTEM_RELIABILITY  - completed runs of core workflows in the last 24 h
2. DATA_COVERAGE       - capabilities with current, permitted data
3. DATA_TRUST          - published datasets that pass validation with clear rights
4. ANALYTICAL_VALIDITY - the computation test suite on main (not edge)
5. SIGNAL_PERFORMANCE  - walk-forward gate and SPA results versus baselines
6. WEBSITE_FUNCTIONALITY - only from a recorded browser check, else unmeasured
7. TELEGRAM_DELIVERY   - a message accepted with its message_id (ops digest
                         delivery log), else Bot API checks of the delivery audit

Standard library only; it reads published files and the GitHub Actions
API with the workflow token. Missing evidence is reported as UNMEASURED,
never as zero or as a pass.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.platform_scorecards.v1"
CORE_WORKFLOWS = (
    "options-radar.yml", "stock-radar.yml", "options-contract-radar.yml", "fast-explosion-radar.yml",
    "classical-direction-radar.yml", "index-radar.yml", "stock-watch-charts.yml", "public-macro.yml",
    "site-evidence-strength.yml", "free-gex-validation.yml", "market-orchestrator.yml",
)
# Capability -> (file, how it counts as available)
CAPABILITIES = {
    "index_prices": "index_radar.json",
    "stock_charts": "stock_watch_charts.json",
    "liquidity_volume": "liquidity_map.json",
    "options_analytics": "options_analytics.json",
    "spx_gamma": "free_gex_validation.json",
    "explosion_discovery": "explosion_hunter.json",
    "classical_direction": "classical_direction.json",
    "news_and_events": "free_public_intelligence.json",
    "issuer_filings": "sec_filing_pulse.json",
    "macro_positioning": "public_macro.json",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _metric(status: str, value: float | None, unit: str, evidence: Any, method: str, note_ar: str) -> dict[str, Any]:
    return {"status": status, "value": value, "unit": unit, "evidence": evidence, "method": method,
            "note_ar": note_ar}


def github_runs(repo: str, token: str, workflow: str, since: datetime) -> list[dict[str, Any]] | None:
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs"
           f"?branch=main&per_page=100&created=>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError):
        return None
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    return runs if isinstance(runs, list) else None


def reliability(runs_by_workflow: dict[str, list[dict[str, Any]] | None]) -> dict[str, Any]:
    if not runs_by_workflow or all(v is None for v in runs_by_workflow.values()):
        return _metric("UNMEASURED", None, "percent", {}, "GitHub Actions API unavailable", "تعذر قراءة سجل التشغيل.")
    evidence, success, failed = {}, 0, 0
    for workflow, runs in runs_by_workflow.items():
        if runs is None:
            evidence[workflow] = "api_unavailable"
            continue
        counts: dict[str, int] = {}
        for run in runs:
            if run.get("status") != "completed":
                continue
            key = str(run.get("conclusion") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        evidence[workflow] = counts
        success += counts.get("success", 0)
        failed += sum(counts.get(k, 0) for k in ("failure", "timed_out", "startup_failure"))
    total = success + failed
    value = round(100 * success / total, 1) if total else None
    return _metric("MEASURED" if total else "UNMEASURED", value, "percent of completed runs (24 h)", evidence,
                   "success / (success + failure + timeout) over core workflows; cancelled and skipped excluded",
                   "نجاح التشغيل لا يعني توفر البيانات؛ المسارات المتوقفة بسبب الترخيص تنجح لكنها لا تنتج إشارات.")


def coverage(data_dir: Path, now: datetime) -> dict[str, Any]:
    states = {}
    for capability, name in CAPABILITIES.items():
        payload = _load(data_dir / name)
        if not isinstance(payload, dict):
            states[capability] = "SOURCE_UNAVAILABLE"
            continue
        status = str(payload.get("status") or "").upper()
        engines = payload.get("integrated_engines", {}) if isinstance(payload.get("integrated_engines"), dict) else {}
        if status == "SOURCE_TERMS_BLOCKED" or any(
                isinstance(v, dict) and v.get("status") == "SOURCE_TERMS_BLOCKED" for v in engines.values()):
            states[capability] = "LICENSE_BLOCKED"
            continue
        if status == "STALE":
            states[capability] = "STALE"
            continue
        if status in {"UNAVAILABLE", "FAILED"}:
            states[capability] = "SOURCE_UNAVAILABLE"
            continue
        stamp = _parse(payload.get("generated_at"))
        if stamp is None:
            states[capability] = "VALIDATION_FAILED"
        elif now - stamp > timedelta(hours=36):
            states[capability] = "STALE"
        else:
            states[capability] = "AVAILABLE"
    available = sum(v == "AVAILABLE" for v in states.values())
    return _metric("MEASURED", round(100 * available / len(states), 1), "percent of capabilities", states,
                   "a capability counts only when its published file is current, permitted and validated by timestamp",
                   "التغطية تقيس توفر البيانات المسموح بها، لا جودتها التنبؤية.")


def trust(hub: Any) -> dict[str, Any]:
    if not isinstance(hub, dict) or not isinstance(hub.get("datasets"), list):
        return _metric("UNMEASURED", None, "percent", {}, "data_hub.json missing", "كتالوج البيانات غير متاح.")
    rows = [r for r in hub["datasets"] if r.get("present")]
    clean = [r for r in rows if r.get("validation") == "PASS" and r.get("rights_status") == "OK_FOR_STATED_USE"]
    evidence = {r["file"]: f"{r.get('validation')}/{r.get('rights_status')}" for r in rows}
    value = round(100 * len(clean) / len(rows), 1) if rows else None
    return _metric("MEASURED" if rows else "UNMEASURED", value, "percent of published datasets", evidence,
                   "validation PASS and rights OK_FOR_STATED_USE (blocked, restricted and unknown rights do not count)",
                   "الثقة هنا تعني صحة البنية ووضوح حق الاستخدام، لا دقة السعر.")


def validity(test_runs: list[dict[str, Any]] | None) -> dict[str, Any]:
    completed = [r for r in test_runs or [] if r.get("status") == "completed" and r.get("conclusion")]
    if not completed:
        return _metric("UNMEASURED", None, "status", {}, "no completed CI run on main read",
                       "تعذر قراءة نتيجة اختبارات الحساب.")
    # An in-progress run has no verdict yet; judge the latest finished one.
    latest = max(completed, key=lambda r: str(r.get("created_at")))
    conclusion = latest.get("conclusion")
    return _metric("PASSING" if conclusion == "success" else "FAILING", None, "status",
                   {"run_id": latest.get("id"), "conclusion": conclusion, "at": latest.get("created_at")},
                   "latest test workflow on main (Greeks oracle, gamma clock, guards, parsers)",
                   "نجاح الاختبارات يثبت صحة الحسابات على حالات معروفة، لا وجود أفضلية تداول.")


def signal_performance(walk_forward: Any, model_lab: Any) -> dict[str, Any]:
    evidence = {}
    if isinstance(walk_forward, dict):
        evidence["walk_forward"] = {"status": walk_forward.get("status"),
                                    "research_passed": walk_forward.get("research_passed")}
    if isinstance(model_lab, dict):
        for key in ("spa", "spa_short"):
            block = model_lab.get(key)
            if isinstance(block, dict):
                evidence[key] = {"pvalue_consistent": block.get("pvalue_consistent"), "baseline": block.get("baseline")}
    if not evidence:
        return _metric("UNMEASURED", None, "status", {}, "no validation report", "لا يوجد تقرير تحقق منشور.")
    proven = bool(evidence.get("walk_forward", {}).get("research_passed")) and any(
        isinstance(v, dict) and isinstance(v.get("pvalue_consistent"), (int, float)) and v["pvalue_consistent"] < 0.05
        for k, v in evidence.items() if k.startswith("spa"))
    return _metric("EDGE_PROVEN" if proven else "NO_PROVEN_EDGE", None, "status", evidence,
                   "walk-forward research gate AND Hansen SPA p < 0.05 versus the same-side baseline",
                   "لا توجد أفضلية مثبتة حتى الآن؛ لا تُعرض إشارات كتوصيات تنفيذية.")


def website(smoke: Any) -> dict[str, Any]:
    if not isinstance(smoke, dict) or not isinstance(smoke.get("pages"), dict):
        return _metric("UNMEASURED", None, "percent", {}, "no recorded browser check",
                       "لا يوجد فحص متصفح مسجل في الإنتاج بعد.")
    pages = smoke["pages"]
    ok = sum(1 for p in pages.values() if isinstance(p, dict) and not p.get("errors") and not p.get("overflow"))
    return _metric("MEASURED", round(100 * ok / len(pages), 1) if pages else None, "percent of pages", pages,
                   "headless browser: no page errors and no horizontal overflow at 390 px",
                   "يقيس سلامة العرض لا صحة البيانات المعروضة.")


def _last_delivery(digest: Any) -> dict[str, Any] | None:
    log = digest.get("delivery_log") if isinstance(digest, dict) else None
    sent = [e for e in log or [] if isinstance(e, dict) and isinstance(e.get("message_id"), int)
            and e["message_id"] > 0 and _parse(e.get("sent_at"))]
    return max(sent, key=lambda e: _parse(e["sent_at"])) if sent else None


def telegram(audit: Any, now: datetime, digest: Any = None) -> dict[str, Any]:
    last = _last_delivery(digest)
    if last is not None and now - _parse(last["sent_at"]) <= timedelta(hours=36):
        return _metric("DELIVERED", None, "status",
                       {"last_sent_at": last["sent_at"], "kind": last.get("kind"), "message_id": last["message_id"],
                        "log": "state/telegram/ops_digest_state.json"},
                       "Telegram accepted a message and returned its message_id (ops digest delivery log)",
                       "Telegram قبل رسالة فعلية وأعاد رقمها؛ هذا لا يثبت أن المستخدم قرأها.")
    if not isinstance(audit, dict):
        return _metric("UNMEASURED", None, "status", {}, "no delivery audit", "لا يوجد سجل تسليم.")
    checked = _parse(audit.get("checked_at"))
    fresh = checked is not None and now - checked <= timedelta(hours=24)
    accepted = audit.get("bot_api_responded") is True and audit.get("destination_api_verified") is True
    evidence = {k: audit.get(k) for k in ("checked_at", "status", "sent", "edited", "unchanged",
                                          "bot_api_responded", "destination_api_verified")}
    status = "API_VERIFIED" if accepted and fresh else "STALE" if accepted else "NOT_VERIFIED"
    return _metric(status, None, "status", evidence,
                   "Bot API identity and destination chat verified by the Contract Guardian delivery audit",
                   "قبول Telegram للرسالة لا يثبت أن المستخدم قرأها.")


# Each engine is reported on five separate questions; a green run says
# nothing about the source, the data, the analysis or the alerts.
ENGINES: dict[str, dict[str, Any]] = {
    "fast_explosion": {"label_ar": "رادار الانفجار السريع", "workflow": "fast-explosion-radar.yml",
                       "file": "explosion_hunter.json", "gates": ("nasdaq_web",)},
    "stock_radar": {"label_ar": "رادار الأسهم", "workflow": "stock-radar.yml", "file": "decision_brief.json",
                    "gates": ("nasdaq_web", "yahoo"), "rows": "stocks"},
    "index_radar": {"label_ar": "تحليل المؤشرات", "workflow": "index-radar.yml", "file": "index_radar.json",
                    "gates": ("yahoo",)},
    "classical": {"label_ar": "الاتجاه الكلاسيكي", "workflow": "classical-direction-radar.yml",
                  "file": "classical_direction.json", "gates": ("yahoo",)},
    "catalysts": {"label_ar": "المحفزات الرسمية", "workflow": "catalyst-watchlist.yml", "file": "catalyst_watchlist.json",
                  "gates": (), "rows": "watchlist", "alert_state": "catalyst/catalyst_alert_state.json"},
    "fda": {"label_ar": "أحداث FDA", "workflow": "fda-events.yml", "file": "fda_events.json", "gates": (),
            "alert_state": "fda/fda_alert_state.json"},
    "sec": {"label_ar": "إفصاحات SEC", "workflow": "official-sec-pulse.yml", "file": "sec_filing_pulse.json", "gates": ()},
    "macro": {"label_ar": "الخزانة وCFTC", "workflow": "public-macro.yml", "file": "public_macro.json", "gates": ()},
    "daily_plan": {"label_ar": "خطة اليوم", "workflow": "daily-plan.yml", "file": "daily_plan.json", "gates": ()},
}
ENGINE_WORKFLOWS = tuple(sorted({e["workflow"] for e in ENGINES.values()} - set(CORE_WORKFLOWS)))
WORKING_STATES = {"LIVE", "DELAYED", "HISTORICAL", "RESEARCH_ONLY", "MODEL_ESTIMATED"}
BLOCK_STATUSES = {"SOURCE_TERMS_BLOCKED", "UNAVAILABLE", "SOURCE_UNAVAILABLE"}


def _last_alert(state: Any) -> str | None:
    """Latest Telegram delivery recorded in an alert state: only entries with a message_id count."""
    if not isinstance(state, dict):
        return None
    # top-level "<name>_at" paired with "<name>_message_id" (briefs, notices)
    stamps = [str(v) for k, v in state.items()
              if k.endswith("_at") and state.get(k[:-3] + "_message_id") and isinstance(v, str)]
    for table in ("events", "seen"):
        rows = state.get(table)
        for row in (rows.values() if isinstance(rows, dict) else []):
            if isinstance(row, dict) and row.get("status") == "sent" and row.get("message_id") and row.get("at"):
                stamps.append(str(row["at"]))
    return max(stamps) if stamps else None


def engine_status(data_dir: Path, state_dir: Path, runs: dict[str, list[dict[str, Any]] | None]) -> dict[str, Any]:
    hub = _load(data_dir / "data_hub.json") or {}
    rows = {r.get("file"): r for r in hub.get("datasets") or [] if isinstance(r, dict)}
    gates = hub.get("source_gates") or {}
    out = {}
    for key, spec in ENGINES.items():
        workflow_runs = runs.get(spec["workflow"]) if runs else None
        completed = [r for r in workflow_runs or [] if r.get("status") == "completed"]
        last = max(completed, key=lambda r: str(r.get("created_at") or ""), default=None)
        run = ("API_UNAVAILABLE" if workflow_runs is None else "NO_RUN_24H" if last is None else
               "OK" if last.get("conclusion") in ("success", "skipped") else "FAILED")
        payload = _load(data_dir / spec["file"])
        status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
        closed = [g for g in spec["gates"] if (gates.get(g) or {}).get("allowed") is False]
        source = ("BLOCKED_BY_TERMS" if closed and (status == "SOURCE_TERMS_BLOCKED" or len(closed) == len(spec["gates"]))
                  else "REFUSED_OR_DOWN" if status in BLOCK_STATUSES else
                  "NO_OUTPUT" if payload is None else "AVAILABLE")
        row = rows.get(spec["file"]) or {}
        state = row.get("data_state") or ("DATA_UNAVAILABLE" if payload is None else "UNKNOWN")
        items = payload.get(spec["rows"]) if isinstance(payload, dict) and spec.get("rows") else None
        # freshness is the hub's measured age against the dataset cadence, not the provenance label
        data = ("NONE" if payload is None or state in ("DATA_UNAVAILABLE", "SOURCE_UNAVAILABLE") else
                "STALE" if row.get("freshness") != "FRESH" else
                "EMPTY" if isinstance(items, list) and not items else
                "FRESH" if state in WORKING_STATES else "NOT_USABLE")
        analysis = "COMPUTED" if data == "FRESH" and source == "AVAILABLE" else "NOT_COMPUTED"
        alert_file = spec.get("alert_state")
        alert = (("DELIVERED " + str(_last_alert(_load(state_dir / alert_file)))) if alert_file and
                 _last_alert(_load(state_dir / alert_file)) else "NONE_DELIVERED" if alert_file else "NO_ALERT_PATH")
        verdict = ("متوقف لغياب مصدر مؤهل" if source == "BLOCKED_BY_TERMS" else
                   "متوقف: المصدر رفض الطلب أو لا يستجيب" if source == "REFUSED_OR_DOWN" else
                   "لم يُنتج مخرجات بعد" if source == "NO_OUTPUT" else
                   "البيانات قديمة" if data == "STALE" else
                   "يعمل بلا نتائج حالية" if data == "EMPTY" else
                   "يعمل" if analysis == "COMPUTED" else "غير قابل للاستخدام")
        out[key] = {"label_ar": spec["label_ar"], "verdict_ar": verdict, "run": run, "source": source, "data": data, "data_state": state,
                    "analysis": analysis, "alerts": alert, "closed_gates": closed,
                    "rows": len(items) if isinstance(items, list) else None,
                    "generated_at": row.get("generated_at"),
                    "last_run_at": last.get("created_at") if last else None}
    return out


def build(data_dir: Path, state_dir: Path, runtime_dir: Path, now: datetime,
          runs: dict[str, list[dict[str, Any]] | None], test_runs: list[dict[str, Any]] | None) -> dict[str, Any]:
    strength = _load(data_dir / "site_strength.json")
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "scorecards": {
            "SYSTEM_RELIABILITY": reliability(runs),
            "DATA_COVERAGE": coverage(data_dir, now),
            "DATA_TRUST": trust(_load(data_dir / "data_hub.json")),
            "ANALYTICAL_VALIDITY": validity(test_runs),
            "SIGNAL_PERFORMANCE": signal_performance(_load(state_dir / "stocks/stock_walk_forward.json"),
                                                     _load(data_dir / "explosion_model_lab.json")),
            "WEBSITE_FUNCTIONALITY": website(_load(data_dir / "site_smoke.json")),
            "TELEGRAM_DELIVERY": telegram(_load(runtime_dir / "data/live/guardian_delivery_audit.json"), now,
                                          _load(state_dir / "telegram/ops_digest_state.json")),
        },
        "engines": engine_status(data_dir, state_dir, runs),
        "original_evidence_score": {
            "value": strength.get("strength_score") if isinstance(strength, dict) else None,
            "weights_changed": False,
            "note": "kept as published by site_strength.json with its original weights",
        },
        "combined_score": None,
        "combined_score_note_ar": "لا يوجد رقم مجمّع؛ كل مقياس يُقرأ وحده بدليله.",
        "decision_grade": False,
        "decision_grade_reason_ar": "لا يوجد مصدر أسعار مسموح ولا أفضلية مثبتة؛ المنصة للبحث والمتابعة فقط.",
        "research_only": True,
        "decision_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    repo, token = os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GH_TOKEN", "")
    since = now - timedelta(hours=24)
    runs = ({w: github_runs(repo, token, w, since) for w in (*CORE_WORKFLOWS, *ENGINE_WORKFLOWS)}
            if repo and token else {})
    test_runs = github_runs(repo, token, "test.yml", now - timedelta(days=3)) if repo and token else None
    report = build(args.data_dir, args.state_dir, args.runtime_dir, now, runs, test_runs)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Platform scorecards:", json.dumps({k: (v["status"], v["value"]) for k, v in report["scorecards"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
