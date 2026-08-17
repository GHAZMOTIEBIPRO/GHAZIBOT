from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable

MIN_COVERAGE_60M_PCT = 90.0
MIN_INDEPENDENT_SESSIONS = 10
MIN_TRAIN_SESSIONS = 6
MIN_TRAIN_RECORDS = 60
MIN_OOS_SESSIONS = 4
MIN_OOS_RECORDS = 40
MAX_TOTAL_ADJUSTMENT = 8.0
DECISIVE = frozenset({"success", "failed"})


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _score_band(value: Any) -> str:
    score = _number(value)
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 72:
        return "72-79"
    if score >= 65:
        return "65-71"
    return "below-65"


def _session(row: dict[str, Any]) -> str:
    return str(row.get("signal_session_date") or "").strip()


def _qualified_60m(row: dict[str, Any]) -> bool:
    coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
    if coverage.get("60m") is True:
        return True
    checkpoints = row.get("checkpoints") if isinstance(row.get("checkpoints"), dict) else {}
    point = checkpoints.get("60m") if isinstance(checkpoints.get("60m"), dict) else {}
    return point.get("coverage_qualified") is True


def _return_60m(row: dict[str, Any]) -> float | None:
    checkpoints = row.get("checkpoints") if isinstance(row.get("checkpoints"), dict) else {}
    point = checkpoints.get("60m") if isinstance(checkpoints.get("60m"), dict) else {}
    value = point.get("directional_return_pct")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _eligible_decisive_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    rows: list[dict[str, Any]] = []
    for value in records.values():
        if not isinstance(value, dict):
            continue
        if value.get("signal_session_valid") is not True:
            continue
        if not _session(value) or not _qualified_60m(value):
            continue
        if value.get("audit_status") not in DECISIVE:
            continue
        score = value.get("entry_score")
        if score is None:
            continue
        row = dict(value)
        row["_outcome"] = 1 if value.get("audit_status") == "success" else 0
        row["_score"] = _number(score)
        row["_return_60m"] = _return_60m(value)
        rows.append(row)
    return sorted(rows, key=lambda row: (_session(row), str(row.get("signal_time") or ""), str(row.get("signal_id") or "")))


def _rate_adjustment(rate: float, baseline: float, *, scale: float, cap: float) -> float:
    delta = rate - baseline
    if abs(delta) < 0.08:
        return 0.0
    return round(max(-cap, min(cap, delta * scale)), 2)


def _cohort_adjustments(
    rows: Iterable[dict[str, Any]],
    key_fn,
    *,
    baseline: float,
    minimum: int,
    scale: float,
    cap: float,
) -> dict[str, float]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(key_fn(row) or "unknown"), []).append(row)
    output: dict[str, float] = {}
    for key, group in groups.items():
        if len(group) < minimum:
            output[key] = 0.0
            continue
        rate = sum(int(row["_outcome"]) for row in group) / len(group)
        output[key] = _rate_adjustment(rate, baseline, scale=scale, cap=cap)
    return output


def _train_shadow_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = sum(int(row["_outcome"]) for row in rows) / len(rows) if rows else 0.5
    return {
        "baseline": baseline,
        "score_bands": _cohort_adjustments(
            rows,
            lambda row: row.get("entry_score_band") or _score_band(row.get("entry_score")),
            baseline=baseline,
            minimum=20,
            scale=18.0,
            cap=5.0,
        ),
        "stages": _cohort_adjustments(
            rows,
            lambda row: row.get("entry_stage") or "unknown",
            baseline=baseline,
            minimum=20,
            scale=12.0,
            cap=3.0,
        ),
        "regimes": _cohort_adjustments(
            rows,
            lambda row: row.get("market_regime") or "unknown",
            baseline=baseline,
            minimum=20,
            scale=10.0,
            cap=2.0,
        ),
        "cause_tiers": _cohort_adjustments(
            rows,
            lambda row: row.get("cause_tier") or "unknown",
            baseline=baseline,
            minimum=15,
            scale=10.0,
            cap=2.0,
        ),
    }


def _shadow_adjustment(model: dict[str, Any], row: dict[str, Any]) -> float:
    keys = (
        ("score_bands", str(row.get("entry_score_band") or _score_band(row.get("entry_score")))),
        ("stages", str(row.get("entry_stage") or "unknown")),
        ("regimes", str(row.get("market_regime") or "unknown")),
        ("cause_tiers", str(row.get("cause_tier") or "unknown")),
    )
    adjustment = 0.0
    for group_name, key in keys:
        group = model.get(group_name) if isinstance(model.get(group_name), dict) else {}
        adjustment += _number(group.get(key), 0.0)
    return round(max(-MAX_TOTAL_ADJUSTMENT, min(MAX_TOTAL_ADJUSTMENT, adjustment)), 2)


def _auc(rows: list[dict[str, Any]], score_key: str) -> float | None:
    positives = [row for row in rows if row["_outcome"] == 1]
    negatives = [row for row in rows if row["_outcome"] == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    pairs = 0
    for positive in positives:
        positive_score = _number(positive.get(score_key))
        for negative in negatives:
            negative_score = _number(negative.get(score_key))
            pairs += 1
            if positive_score > negative_score:
                wins += 1.0
            elif positive_score == negative_score:
                wins += 0.5
    return round(wins / pairs, 4) if pairs else None


def _top_quartile(rows: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    if not rows:
        return []
    count = max(1, math.ceil(len(rows) * 0.25))
    return sorted(rows, key=lambda row: (_number(row.get(score_key)), str(row.get("signal_id") or "")), reverse=True)[:count]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "positive_rate": None, "mean_60m_return_pct": None}
    returns = [row["_return_60m"] for row in rows if row.get("_return_60m") is not None]
    return {
        "n": len(rows),
        "positive_rate": round(sum(int(row["_outcome"]) for row in rows) / len(rows), 4),
        "mean_60m_return_pct": round(mean(returns), 4) if returns else None,
    }


@dataclass(frozen=True)
class WalkForwardGate:
    coverage_60m_pct: float
    independent_sessions: int
    upstream_coverage_ready: bool

    @property
    def ready(self) -> bool:
        return (
            self.upstream_coverage_ready
            and self.coverage_60m_pct >= MIN_COVERAGE_60M_PCT
            and self.independent_sessions >= MIN_INDEPENDENT_SESSIONS
        )


def _gate(audit: dict[str, Any]) -> WalkForwardGate:
    coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    promotion = audit.get("promotion_gate") if isinstance(audit.get("promotion_gate"), dict) else {}
    return WalkForwardGate(
        coverage_60m_pct=_number(coverage.get("coverage_60m_pct")),
        independent_sessions=int(_number(coverage.get("independent_60m_sessions"))),
        upstream_coverage_ready=promotion.get("coverage_ready") is True,
    )


def run_stock_walk_forward(audit: dict[str, Any]) -> dict[str, Any]:
    gate = _gate(audit)
    base_report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "EXPANDING_SESSION_WALK_FORWARD",
        "decision_authority": False,
        "live_alert_weights_changed": False,
        "live_promotion_allowed": False,
        "data_policy": {
            "source": "stock_outcome_audit",
            "requires_signal_session_valid": True,
            "requires_qualified_60m": True,
            "decisive_only_for_binary_ranking_metrics": True,
            "random_split_allowed": False,
            "future_session_training_allowed": False,
        },
        "methodology": {
            "minimum_coverage_60m_pct": MIN_COVERAGE_60M_PCT,
            "minimum_independent_sessions": MIN_INDEPENDENT_SESSIONS,
            "minimum_train_sessions": MIN_TRAIN_SESSIONS,
            "minimum_train_records": MIN_TRAIN_RECORDS,
            "minimum_oos_sessions": MIN_OOS_SESSIONS,
            "minimum_oos_records": MIN_OOS_RECORDS,
            "candidate_adjustment_cap": MAX_TOTAL_ADJUSTMENT,
            "candidate_policy": "shadow replica of current cohort-relative stock adjustment; entry evidence state remains research-only",
        },
        "gate": {
            "coverage_60m_pct": round(gate.coverage_60m_pct, 2),
            "independent_60m_sessions": gate.independent_sessions,
            "upstream_coverage_ready": gate.upstream_coverage_ready,
            "ready": gate.ready,
        },
        "research_passed": False,
    }

    if not gate.ready:
        reasons: list[str] = []
        if gate.coverage_60m_pct < MIN_COVERAGE_60M_PCT:
            reasons.append(f"60m coverage {gate.coverage_60m_pct:.2f}% < {MIN_COVERAGE_60M_PCT:.0f}%")
        if gate.independent_sessions < MIN_INDEPENDENT_SESSIONS:
            reasons.append(f"independent sessions {gate.independent_sessions} < {MIN_INDEPENDENT_SESSIONS}")
        if not gate.upstream_coverage_ready:
            reasons.append("upstream outcome-audit promotion gate is closed")
        return {
            **base_report,
            "status": "NOT_READY",
            "reasons": reasons,
            "folds": [],
            "metrics": {"oos_records": 0, "oos_sessions": 0},
        }

    rows = _eligible_decisive_rows(audit)
    sessions = sorted({_session(row) for row in rows})
    folds: list[dict[str, Any]] = []
    oos_rows: list[dict[str, Any]] = []

    for test_index in range(MIN_TRAIN_SESSIONS, len(sessions)):
        train_sessions = sessions[:test_index]
        test_session = sessions[test_index]
        train_rows = [row for row in rows if _session(row) in set(train_sessions)]
        test_rows = [dict(row) for row in rows if _session(row) == test_session]
        if len(train_rows) < MIN_TRAIN_RECORDS or not test_rows:
            continue

        model = _train_shadow_model(train_rows)
        for row in test_rows:
            row["_baseline_score"] = row["_score"]
            row["_shadow_adjustment"] = _shadow_adjustment(model, row)
            row["_adjusted_score"] = row["_score"] + row["_shadow_adjustment"]
            row["_test_session"] = test_session
        oos_rows.extend(test_rows)
        folds.append(
            {
                "test_session": test_session,
                "train_sessions": train_sessions,
                "train_records": len(train_rows),
                "test_records": len(test_rows),
                "train_baseline_positive_rate": round(model["baseline"], 4),
                "baseline_auc": _auc(test_rows, "_baseline_score"),
                "adjusted_auc": _auc(test_rows, "_adjusted_score"),
                "baseline_top_quartile": _summary(_top_quartile(test_rows, "_baseline_score")),
                "adjusted_top_quartile": _summary(_top_quartile(test_rows, "_adjusted_score")),
            }
        )

    if not folds:
        return {
            **base_report,
            "status": "INSUFFICIENT_OOS",
            "reasons": ["coverage gate opened but no eligible expanding-session fold has >=60 prior decisive records"],
            "folds": [],
            "metrics": {"oos_records": 0, "oos_sessions": 0, "eligible_decisive_records": len(rows)},
        }

    baseline_top: list[dict[str, Any]] = []
    adjusted_top: list[dict[str, Any]] = []
    session_robustness: list[bool] = []
    for test_session in sorted({_session(row) for row in oos_rows}):
        session_rows = [row for row in oos_rows if _session(row) == test_session]
        base = _top_quartile(session_rows, "_baseline_score")
        adjusted = _top_quartile(session_rows, "_adjusted_score")
        baseline_top.extend(base)
        adjusted_top.extend(adjusted)
        all_rate = _summary(session_rows)["positive_rate"]
        adjusted_rate = _summary(adjusted)["positive_rate"]
        if all_rate is not None and adjusted_rate is not None:
            session_robustness.append(adjusted_rate >= all_rate)

    overall = _summary(oos_rows)
    baseline_top_summary = _summary(baseline_top)
    adjusted_top_summary = _summary(adjusted_top)
    baseline_auc = _auc(oos_rows, "_baseline_score")
    adjusted_auc = _auc(oos_rows, "_adjusted_score")
    robustness_rate = round(sum(session_robustness) / len(session_robustness), 4) if session_robustness else None

    criteria = {
        "minimum_oos_records": len(oos_rows) >= MIN_OOS_RECORDS,
        "minimum_oos_sessions": len(folds) >= MIN_OOS_SESSIONS,
        "adjusted_auc_at_least_0_55": adjusted_auc is not None and adjusted_auc >= 0.55,
        "adjusted_auc_not_worse_than_baseline_minus_0_01": (
            adjusted_auc is not None and baseline_auc is not None and adjusted_auc >= baseline_auc - 0.01
        ),
        "adjusted_top_quartile_positive_rate_lift_at_least_3pp": (
            adjusted_top_summary["positive_rate"] is not None
            and overall["positive_rate"] is not None
            and adjusted_top_summary["positive_rate"] >= overall["positive_rate"] + 0.03
        ),
        "adjusted_top_quartile_not_worse_than_baseline_by_more_than_2pp": (
            adjusted_top_summary["positive_rate"] is not None
            and baseline_top_summary["positive_rate"] is not None
            and adjusted_top_summary["positive_rate"] >= baseline_top_summary["positive_rate"] - 0.02
        ),
        "adjusted_top_quartile_mean_60m_return_positive": (
            adjusted_top_summary["mean_60m_return_pct"] is not None
            and adjusted_top_summary["mean_60m_return_pct"] > 0.0
        ),
        "session_robustness_at_least_half": robustness_rate is not None and robustness_rate >= 0.5,
    }
    passed = all(criteria.values())

    return {
        **base_report,
        "status": "PASSED_RESEARCH_GATE" if passed else "FAILED_RESEARCH_GATE",
        "reasons": [],
        "folds": folds,
        "metrics": {
            "eligible_decisive_records": len(rows),
            "oos_records": len(oos_rows),
            "oos_sessions": len(folds),
            "overall_oos": overall,
            "baseline_auc": baseline_auc,
            "adjusted_auc": adjusted_auc,
            "baseline_top_quartile": baseline_top_summary,
            "adjusted_top_quartile": adjusted_top_summary,
            "session_robustness_rate": robustness_rate,
        },
        "pass_criteria": criteria,
        "research_passed": passed,
        # Deliberately remains false even if research_passed becomes true.
        "live_promotion_allowed": False,
    }
