"""Reproducible 0–100 *research evidence readiness* score for GHAZI RADAR.

Not a profitability score, prediction success percentage, user experience grade,
tradable-signal quality claim, or a test of the deployed webpage. Explicitly
withholds points for unverified independent quotes, SEC access and OPRA NBBO.
No network, API tokens, model downloads or user-created evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 4_000_000
WEIGHTS = {
    "charts": 25,
    "independent_prices": 20,
    "issuer_filings": 15,
    "options_market_data": 15,
    "walk_forward": 15,
    "feed_operations": 10,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _fresh(data: dict, now: datetime, hours: int) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        dt = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
        if dt.tzinfo is None or now.tzinfo is None:
            return False
        age = (now.astimezone(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
        return -300 <= age <= hours * 3600
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _int(value: Any, *, cap: int = 1_000_000) -> int | None:
    if type(value) is int and 0 <= value <= cap:
        return value
    return None


def _float(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100:
        return float(value)
    return None


def score(
    *, charts: dict, agreement: dict, sec: dict, free_options: dict,
    walk_forward: dict, now: datetime,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    fresh_charts = _fresh(charts, now, 48) and (
        charts.get("schema") == "ghazi.stock_charts.v1"
        and charts.get("quote_execution_eligible") is False
        and charts.get("provider_source_family") == "yahoo")
    fresh_agreement = _fresh(agreement, now, 48) and (
        agreement.get("schema") == "ghazi.source_consensus_status.v1"
        and agreement.get("quote_execution_eligible") is False)
    fresh_sec = _fresh(sec, now, 72) and (
        sec.get("schema") == "ghazi.sec_issuer_pulse.v1"
        and sec.get("policy", {}).get("positive_news_inferred") is False)
    fresh_free = _fresh(free_options, now, 72) and (
        free_options.get("schema") == "ghazi.free_options_source_pulse.v1"
        and free_options.get("research_only") is True
        and free_options.get("option_execution_eligible") is False
        and free_options.get("trading_authority") is False)
    points: dict[str, float] = {key: 0.0 for key in WEIGHTS}
    detail: dict[str, str] = {}

    cov = charts.get("coverage", {}) if isinstance(charts.get("coverage"), dict) else {}
    requested = _int(cov.get("requested"), cap=100)
    if fresh_charts and requested and requested >= 1:
        counts = [
            _int(cov.get(key), cap=100)
            for key in ("with_daily", "with_1h", "with_15m", "with_5m")
        ]
        if all(count is not None and count <= requested for count in counts):
            points["charts"] = round(sum(6.25 * count / requested for count in counts), 2)
    detail["charts"] = (
        f"{requested or 0} requested research charts; validated timeframe coverage"
        if fresh_charts else "No source-dated recent chart report"
    )

    # A Yahoo-only family cannot receive independent cross-provider points.
    # Do not invent agreement from a second Yahoo wrapper or an unlicensed key.
    independ = _int(agreement.get("independent_confirmations"), cap=50)
    agreement_verified = fresh_agreement and (
        agreement.get("independent_price_comparison") == "VERIFIED_LICENSED"
        and agreement.get("licensed_independent_non_display_analysis") is True
        and independ is not None and independ >= 2
        and agreement.get("massive_market_data_published") is False
        and agreement.get("quote_execution_eligible") is False)
    if agreement_verified:
        points["independent_prices"] = 20
    detail["independent_prices"] = (
        "Two licensed, independent price sources actually cross-checked"
        if agreement_verified else "Independent price confirmation not verified"
    )

    filings = sec.get("filings") if isinstance(sec.get("filings"), list) else []
    verified = sum(1 for item in filings[:150] if isinstance(item, dict)
                   and item.get("original_filing_confirmed") is True
                   and item.get("research_only") is True
                   and isinstance(item.get("accession_number"), str))
    inspected = _int(sec.get("coverage", {}).get("issuers_inspected")
                     if isinstance(sec.get("coverage"), dict) else None)
    if fresh_sec and sec.get("status") in ("OK", "PARTIAL") and verified > 0:
        points["issuer_filings"] = 15
        detail["issuer_filings"] = "Direct SEC issuer filings confirmed"
    elif fresh_sec and sec.get("status") == "NO_RECENT_FILINGS" and inspected:
        points["issuer_filings"] = 7
        detail["issuer_filings"] = "Official issuer feed reachable; no new verified filings"
    else:
        f = free_options.get("filingpulse", {}) if fresh_free else {}
        events = f.get("events") if isinstance(f, dict) else None
        valid_third_party = (
            isinstance(events, list)
            and f.get("status") == "THIRD_PARTY_RESEARCH_ONLY"
            and any(isinstance(item, dict)
                    and item.get("third_party_source") == "FILINGPULSE_SEC_DERIVED"
                    and item.get("official_sec_api_response_verified") is False
                    and item.get("positive_catalyst_verified") is False
                    for item in events[:45]))
        if valid_third_party:
            points["issuer_filings"] = 5
        detail["issuer_filings"] = (
            "Third-party SEC-derived metadata, not a direct SEC confirmation"
            if valid_third_party else "No recently verified issuer filing access"
        )

    oi = free_options.get("occ_open_interest", {}) if fresh_free else {}
    values = oi.get("open_interest") if isinstance(oi, dict) else None
    valid_oi = (isinstance(oi, dict)
                and oi.get("status") == "HISTORICAL_DAILY_AGGREGATE"
                and oi.get("not_live_quote") is True
                and oi.get("not_trade_flow") is True
                and isinstance(values, dict) and 0 < len(values) <= 50
                and all(isinstance(symbol, str)
                        and _int(count, cap=10**12) is not None
                        for symbol, count in values.items()))
    if valid_oi:
        try:
            day = datetime.strptime(str(oi.get("report_date")), "%Y-%m-%d")
            diff = (now.astimezone(timezone.utc).date() - day.date()).days
            valid_oi = 0 <= diff <= 7
        except ValueError:
            valid_oi = False
    if valid_oi:
        points["options_market_data"] = 5
    # 10 points are reserved for validated licensed OPRA execution quotes,
    # which the free provenance report explicitly refuses to certify.
    detail["options_market_data"] = (
        "Historical OCC OI context; not executable NBBO"
        if valid_oi else "Neither valid OCC OI nor licensed executable option quotes"
    )

    gate = walk_forward.get("gate") if isinstance(walk_forward.get("gate"), dict) else {}
    metrics = (walk_forward.get("metrics")
               if isinstance(walk_forward.get("metrics"), dict) else {})
    allowed = (walk_forward.get("mode") == "EXPANDING_SESSION_WALK_FORWARD"
               and walk_forward.get("decision_authority") is False
               and walk_forward.get("live_promotion_allowed") is False
               and walk_forward.get("data_policy", {}).get("random_split_allowed") is False
               and walk_forward.get("data_policy", {}).get(
                   "future_session_training_allowed") is False)
    cov_pct = _float(gate.get("coverage_60m_pct"))
    independent_sessions = _int(gate.get("independent_60m_sessions"))
    out_sessions = _int(metrics.get("oos_sessions"))
    out_records = _int(metrics.get("oos_records"))
    if allowed and cov_pct is not None and independent_sessions is not None:
        points["walk_forward"] = round(
            6 * min(1, cov_pct / 90) + 2 * min(1, independent_sessions / 10), 2
        )
        if (gate.get("ready") is True and walk_forward.get("research_passed") is True
                and cov_pct >= 90 and independent_sessions >= 10
                and out_sessions is not None and out_sessions >= 4
                and out_records is not None and out_records >= 40):
            points["walk_forward"] = round(points["walk_forward"] + 7, 2)
    detail["walk_forward"] = (
        "Research sample coverage, NOT prediction accuracy or out-of-sample edge"
        if allowed else "No valid non-execution walk-forward evidence"
    )

    points["feed_operations"] = (
        (4 if fresh_charts else 0)
        + (2 if fresh_agreement else 0)
        + (2 if fresh_sec else 0)
        + (2 if fresh_free else 0)
    )
    detail["feed_operations"] = (
        "Publication freshness only; CI pass, browser UX and uptime not independently scored"
    )
    total = round(sum(points.values()))
    if total < 0 or total > 100:
        raise AssertionError("Invalid readiness points")
    components = [
        {"id": key, "earned": points[key], "maximum": WEIGHTS[key],
         "reason": detail[key]}
        for key in WEIGHTS
    ]
    return {
        "schema": "ghazi.evidence_strength.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "strength_score": total,
        "score_basis": "RESEARCH_DATA_AND_VALIDATION_READINESS",
        "score_is_prediction_win_rate": False,
        "score_is_realized_return": False,
        "score_includes_unverified_live_quotes": False,
        "score_includes_visual_ui_audit": False,
        "execution_authority": False,
        "research_only": True,
        "weights_sum": sum(WEIGHTS.values()),
        "components": components,
        "data_freshness": {
            "chart_report_recent": fresh_charts,
            "independent_source_status_recent": fresh_agreement,
            "official_filings_report_recent": fresh_sec,
            "alternative_filing_options_report_recent": fresh_free,
            "walk_forward_report_timestamp_verified": False,
        },
        "critical_gaps": [
            key for key in ("independent_prices", "issuer_filings",
                            "options_market_data", "walk_forward")
            if points[key] < WEIGHTS[key]
        ],
        "notes": [
            "Score is source-backed research-system readiness, NOT predictive accuracy.",
            "UI aesthetics, end-to-end browser interaction and Vercel uptime are untested.",
            "A historical OOS report without generation timestamp cannot verify recency.",
            "Missing or stale data lowers points; empty reports cannot be promoted.",
            "License-restricted model downloads, Kaggle datasets or LEAN paid CLI are not automatic.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("charts", "agreement", "sec", "free-options", "walk-forward"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = score(
        charts=_read(args.charts), agreement=_read(args.agreement),
        sec=_read(args.sec), free_options=_read(args.free_options),
        walk_forward=_read(args.walk_forward),
        now=datetime.now(timezone.utc),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(args.output)
    print("EVIDENCE READINESS", report["strength_score"], "/100")
    for item in report["components"]:
        print(item["id"], item["earned"], "/", item["maximum"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
