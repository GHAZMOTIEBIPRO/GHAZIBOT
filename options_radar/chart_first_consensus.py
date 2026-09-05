from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .options_consensus import score_contract_strict


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


def score_contract_chart_first(
    row: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    """Add bounded chart/strike evidence on top of the existing strict score.

    Existing execution, liquidity, gamma and provider blockers remain intact.
    Chart evidence cannot rescue a contract rejected by those hard gates.
    """
    score, base_reasons, base_blockers = score_contract_strict(row)
    reasons = list(base_reasons)
    blockers = list(base_blockers)
    timeframes = int(_number(row.get("chart_available_timeframes")))
    alignment = _number(row.get("chart_side_alignment"))
    strike_intel = _number(row.get("strike_intelligence_score"), 50.0)
    institutional_proxy = _number(row.get("institutional_activity_proxy_score"), 50.0)
    expected_ratio_raw = row.get("strike_distance_expected_move_ratio")
    expected_ratio = (
        _number(expected_ratio_raw, float("nan"))
        if expected_ratio_raw is not None
        else float("nan")
    )

    if timeframes < 2:
        score -= 12.0
        blockers.append("chart_multiframe_unavailable")
    else:
        chart_adjustment = max(-8.0, min(8.0, alignment * 8.0))
        score += chart_adjustment
        reasons.append(
            f"chart-first {timeframes}TF alignment {alignment:+.2f} ({chart_adjustment:+.1f})"
        )
        if alignment <= -0.40:
            score -= 7.0
            blockers.append("chart_strongly_opposes_side")
        elif alignment >= 0.40:
            reasons.append("1D/15m/5m chart aligns with contract side")

    strike_adjustment = max(-4.0, min(4.0, (strike_intel - 50.0) * 0.08))
    score += strike_adjustment
    if strike_intel >= 68:
        reasons.append(f"strike intelligence {strike_intel:.0f}/100")

    # This is explicitly only a price/volume proxy for unusual participation.
    # It can add at most two points and can never prove institution/dealer flow.
    proxy_adjustment = max(-2.0, min(2.0, (institutional_proxy - 50.0) * 0.04))
    score += proxy_adjustment
    if institutional_proxy >= 65:
        reasons.append(f"institutional activity proxy {institutional_proxy:.0f}/100")

    if math.isfinite(expected_ratio) and expected_ratio > 1.35:
        score -= 8.0
        blockers.append("strike_outside_expected_move")

    return round(_clamp(score), 2), reasons, list(dict.fromkeys(blockers))


def build_chart_first_directional_signals(
    contracts: list[dict[str, Any]],
    *,
    minimum_score: float = 85.0,
    minimum_side_edge: float = 6.0,
    max_signals: int = 8,
) -> list[dict[str, Any]]:
    """Choose one side/strike only after multi-timeframe chart confirmation."""
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in contracts:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").upper().strip()
        side = str(raw.get("option_type") or "").lower()
        if not symbol or side not in {"call", "put"}:
            continue
        row = dict(raw)
        strict_score, reasons, blockers = score_contract_chart_first(row)
        row["strict_score"] = strict_score
        row["strict_grade"] = _grade(strict_score)
        row["strict_reasons"] = reasons
        row["strict_blockers"] = blockers
        by_symbol[symbol].append(row)

    hard_blockers = {
        "provider_quote_disagreement",
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
        "chart_multiframe_unavailable",
        "chart_strongly_opposes_side",
        "strike_outside_expected_move",
    }
    signals: list[dict[str, Any]] = []
    for symbol, rows in by_symbol.items():
        side_rows: dict[str, list[dict[str, Any]]] = {"call": [], "put": []}
        for row in rows:
            side_rows[str(row.get("option_type") or "").lower()].append(row)
        for side in side_rows:
            side_rows[side].sort(
                key=lambda item: (
                    _number(item.get("strict_score")),
                    _number(item.get("strike_intelligence_score")),
                    _number(item.get("flow_momentum_score")),
                ),
                reverse=True,
            )

        def side_score(side: str) -> float:
            candidates = side_rows[side][:2]
            if not candidates:
                return 0.0
            best = _number(candidates[0].get("strict_score"))
            second = (
                _number(candidates[1].get("strict_score"))
                if len(candidates) > 1
                else best - 5.0
            )
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
        signal["free_alert_eligible"] = (
            strict >= minimum_score and signal["signal_grade"] in {"A", "A+"}
        )
        signal["selection_policy"] = (
            "chart_first_one_side_one_contract_per_symbol_v1"
        )
        signal["chart_first_required"] = True
        signals.append(signal)

    signals.sort(
        key=lambda row: (
            _number(row.get("strict_score")),
            _number(row.get("side_consensus_score")),
            _number(row.get("strike_intelligence_score")),
            _number(row.get("flow_momentum_score")),
        ),
        reverse=True,
    )
    return signals[: max(1, max_signals)]
