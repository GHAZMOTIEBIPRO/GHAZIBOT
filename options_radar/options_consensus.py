from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _grade(score: float) -> str:
    if score >= 91:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 80:
        return "B+"
    return "B"


def score_contract_strict(row: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    score = _number(row.get("score"))
    flow = _number(row.get("flow_momentum_score"))
    data_quality = _number(row.get("data_quality"), 0.5) * 100.0
    execution = _number(row.get("execution_score")) / 30.0 * 100.0
    rr = _number(row.get("reward_risk_1"))
    spread = _number(row.get("spread_pct"), 1.0)
    vol_oi = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    volume = _number(row.get("volume"))
    oi = _number(row.get("open_interest"))
    delta = abs(_number(row.get("delta")))
    dte = _number(row.get("dte"))
    gamma_concentration = _number(row.get("gamma_concentration_pct"))
    gamma_alignment = _number(row.get("gamma_context_alignment"))
    gamma_coverage = _number(row.get("gamma_coverage_pct"))
    oi_coverage = _number(row.get("oi_coverage_pct"))
    occ = row.get("occ_side_context") if isinstance(row.get("occ_side_context"), dict) else {}
    occ_bonus = _number(occ.get("bonus"))
    learning = (
        max(-4.0, min(4.0, _number(row.get("learning_adjustment"))))
        if row.get("learning_active") is True
        else 0.0
    )

    rr_fit = _clamp((rr - 0.8) / 1.2 * 100.0)
    gamma_fit = _clamp(gamma_concentration * 3.0 + max(0.0, gamma_alignment) * 35.0)
    liquidity_fit = _clamp(min(volume / 1500.0, 1.0) * 45.0 + min(oi / 3000.0, 1.0) * 35.0 + min(vol_oi / 3.0, 1.0) * 20.0)

    strict = (
        score * 0.30
        + flow * 0.22
        + execution * 0.12
        + data_quality * 0.10
        + gamma_fit * 0.10
        + liquidity_fit * 0.10
        + rr_fit * 0.06
        + occ_bonus
        + learning
    )

    blockers: list[str] = []
    reasons: list[str] = []
    if spread > 0.10:
        strict -= 9.0
        blockers.append("spread_above_10pct")
    if not 0.35 <= delta <= 0.62:
        strict -= 8.0
        blockers.append("delta_outside_strict_window")
    if not 7 <= dte <= 60:
        strict -= 6.0
        blockers.append("dte_outside_strict_window")
    if volume < 250:
        strict -= 8.0
        blockers.append("option_volume_below_250")
    if oi < 150:
        strict -= 7.0
        blockers.append("oi_below_150")
    if vol_oi < 1.2:
        strict -= 8.0
        blockers.append("vol_oi_below_1_2")
    if flow < 62:
        strict -= 9.0
        blockers.append("flow_below_62")
    if gamma_coverage < 45 or oi_coverage < 45:
        strict -= 7.0
        blockers.append("gamma_or_oi_coverage_weak")
    if gamma_alignment < -0.22:
        strict -= 7.0
        blockers.append("gamma_proxy_opposes_side")
    if occ.get("opposed") is True:
        strict -= 3.0
        blockers.append("occ_daily_volume_opposes_side")
    if rr < 1.0:
        strict -= 8.0
        blockers.append("reward_risk_below_1")

    strict = _clamp(strict)
    if score >= 80:
        reasons.append(f"contract score {score:.0f}/100")
    if flow >= 70:
        reasons.append(f"flow momentum {flow:.0f}/100")
    if spread <= 0.07:
        reasons.append(f"spread {spread * 100:.1f}%")
    if gamma_concentration > 0:
        reasons.append(f"gamma concentration {gamma_concentration:.1f}%")
    if gamma_alignment >= 0.15:
        reasons.append("gamma positioning proxy aligned")
    if occ.get("aligned") is True:
        reasons.append(f"OCC daily volume aligned {occ.get('dominance_ratio')}x")
    if rr >= 1.2:
        reasons.append(f"R/R {rr:.2f}")
    if abs(learning) >= 0.05:
        reasons.append(f"validated learning adjustment {learning:+.2f}")
    return round(strict, 2), reasons, blockers


def build_directional_signals(
    contracts: list[dict[str, Any]],
    *,
    minimum_score: float = 85.0,
    minimum_side_edge: float = 6.0,
    max_signals: int = 8,
) -> list[dict[str, Any]]:
    """Choose exactly one CALL or PUT side per symbol, then one best contract.

    This layer never turns an ambiguous symbol into a signal. It is deliberately
    selective: zero signals is a valid result. Learned adjustments are bounded
    and can never override the hard execution/risk blockers below.
    """
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in contracts:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        side = str(raw.get("option_type") or "").lower()
        if symbol and side in {"call", "put"}:
            row = dict(raw)
            strict_score, reasons, blockers = score_contract_strict(row)
            row["strict_score"] = strict_score
            row["strict_grade"] = _grade(strict_score)
            row["strict_reasons"] = reasons
            row["strict_blockers"] = blockers
            by_symbol[symbol].append(row)

    signals: list[dict[str, Any]] = []
    for symbol, rows in by_symbol.items():
        side_rows: dict[str, list[dict[str, Any]]] = {"call": [], "put": []}
        for row in rows:
            side_rows[str(row.get("option_type") or "").lower()].append(row)
        for side in side_rows:
            side_rows[side].sort(key=lambda item: (_number(item.get("strict_score")), _number(item.get("flow_momentum_score"))), reverse=True)

        def side_score(side: str) -> float:
            candidates = side_rows[side][:2]
            if not candidates:
                return 0.0
            best = _number(candidates[0].get("strict_score"))
            second = _number(candidates[1].get("strict_score")) if len(candidates) > 1 else best - 5.0
            return best * 0.78 + second * 0.22

        call_score = side_score("call")
        put_score = side_score("put")
        if call_score <= 0 and put_score <= 0:
            continue
        winner = "call" if call_score > put_score else "put"
        winner_score = max(call_score, put_score)
        loser_score = min(call_score, put_score)
        edge = winner_score - loser_score if loser_score > 0 else 12.0
        best = side_rows[winner][0] if side_rows[winner] else None
        if best is None:
            continue
        strict = _number(best.get("strict_score"))
        hard_blockers = {
            "spread_above_10pct",
            "delta_outside_strict_window",
            "dte_outside_strict_window",
            "option_volume_below_250",
            "oi_below_150",
            "vol_oi_below_1_2",
            "flow_below_62",
            "gamma_or_oi_coverage_weak",
            "gamma_proxy_opposes_side",
            "reward_risk_below_1",
        }
        blockers = set(best.get("strict_blockers") or [])
        if strict < minimum_score or winner_score < minimum_score - 1.0:
            continue
        if edge < minimum_side_edge and loser_score > 0:
            continue
        if blockers & hard_blockers:
            continue

        signal = dict(best)
        signal["direction"] = winner.upper()
        signal["direction_label"] = "CALL" if winner == "call" else "PUT"
        signal["side_consensus_score"] = round(winner_score, 2)
        signal["opposite_side_score"] = round(loser_score, 2)
        signal["side_edge"] = round(edge, 2)
        signal["signal_grade"] = _grade(strict)
        signal["free_alert_eligible"] = strict >= minimum_score and signal["signal_grade"] in {"A", "A+"}
        signal["selection_policy"] = "one_side_one_contract_per_symbol_strict_consensus"
        signals.append(signal)

    signals.sort(
        key=lambda row: (
            _number(row.get("strict_score")),
            _number(row.get("side_consensus_score")),
            _number(row.get("flow_momentum_score")),
        ),
        reverse=True,
    )
    return signals[: max(1, max_signals)]
