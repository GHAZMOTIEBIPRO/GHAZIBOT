from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_contract(row: dict[str, Any], *, free_threshold: float = 87.0) -> dict[str, Any]:
    """Apply a conservative evidence-quorum gate after contract consensus.

    This is deliberately a gate, not a score booster: hard execution/data
    blockers remain authoritative and weak evidence cannot be converted into
    a production alert merely by a high model score.
    """
    blockers = [str(x) for x in (row.get("strict_blockers") or [])]
    reasons: list[str] = []
    hard_blocked = bool(blockers)

    score = _num(row.get("strict_score") or row.get("score"))
    flow = _num(row.get("flow_momentum_score"))
    data_quality = _num(row.get("data_quality"), 0.0)
    gamma_alignment = _num(row.get("gamma_context_alignment"))
    gamma_coverage = _num(row.get("gamma_coverage_pct"))
    oi_coverage = _num(row.get("oi_coverage_pct"))
    occ = row.get("occ_side_context") if isinstance(row.get("occ_side_context"), dict) else {}
    occ_aligned = occ.get("aligned") is True
    occ_opposed = occ.get("opposed") is True

    if score >= free_threshold:
        reasons.append(f"strict score {score:.0f}≥{free_threshold:.0f}")
    else:
        reasons.append(f"strict score {score:.0f}<{free_threshold:.0f}")

    if flow >= 70:
        reasons.append("flow momentum strong")
    elif flow >= 62:
        reasons.append("flow momentum acceptable")
    else:
        reasons.append("flow momentum weak")

    if gamma_alignment >= 0.15:
        reasons.append("gamma context aligned")
    elif gamma_alignment <= -0.15:
        reasons.append("gamma context opposed")
    else:
        reasons.append("gamma context neutral")

    if occ_aligned:
        reasons.append("OCC side context aligned")
    elif occ_opposed:
        reasons.append("OCC side context opposed")

    # A signal needs independent evidence convergence. Neutral/unknown context
    # is allowed for research, but not enough for an autonomous free alert.
    quorum = 0
    if flow >= 70:
        quorum += 1
    if gamma_alignment >= 0.15:
        quorum += 1
    if occ_aligned:
        quorum += 1
    if data_quality >= 0.80:
        quorum += 1

    conflict = (
        (gamma_alignment <= -0.15 and occ_aligned)
        or (gamma_alignment >= 0.15 and occ_opposed)
        or (gamma_alignment <= -0.22 and flow < 70)
        or (occ_opposed and flow < 70)
    )

    if conflict:
        blockers.append("omega_evidence_conflict")
    if gamma_coverage < 45 or oi_coverage < 45:
        blockers.append("omega_context_coverage_weak")
    if data_quality < 0.80:
        blockers.append("omega_data_quality_below_80pct")
    if quorum < 2:
        blockers.append("omega_evidence_quorum_not_met")
    if score < free_threshold:
        blockers.append("omega_free_threshold_not_met")

    approved = not hard_blocked and not blockers
    return {
        "state": "CONFIRMED" if approved else "NO_TRADE",
        "approved": approved,
        "free_alert_eligible": approved,
        "quorum": quorum,
        "conflict": conflict,
        "reasons": reasons,
        "blockers": sorted(set(blockers)),
        "policy": "Evidence quorum is a hard gate for autonomous free alerts; research rows are retained for learning.",
    }


def apply_omega_gate(signals: list[dict[str, Any]], *, free_threshold: float = 87.0) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in signals:
        row = dict(raw)
        decision = evaluate_contract(row, free_threshold=free_threshold)
        row["omega_decision"] = decision
        row["free_alert_eligible"] = bool(decision["approved"])
        output.append(row)
    return output
