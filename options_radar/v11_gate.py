from __future__ import annotations

from typing import Any

from .execution_confidence import assess_execution_quote
from .omega_decision import evaluate_contract


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_v11_signal(
    row: dict[str, Any],
    *,
    free_threshold: float = 87.0,
    max_quote_age_seconds: float = 120.0,
    require_independent_sources: int = 2,
) -> dict[str, Any]:
    """Unified fail-closed production gate for BLACK BOX Omega V11.

    V11 does not create a bullish/bearish opinion. It verifies whether an
    already-produced contract signal is sufficiently evidenced and executable
    to leave research mode. Missing/ambiguous evidence always fails closed.
    """
    record = dict(row or {})
    omega = evaluate_contract(record, free_threshold=free_threshold)
    execution = assess_execution_quote(
        record,
        max_quote_age_seconds=max_quote_age_seconds,
    ).as_dict()

    blockers = list(omega.get("blockers") or [])
    independent_sources = int(
        _num(
            record.get("fabric_independent_source_count"),
            _num(record.get("fabric_source_count"), 0.0),
        )
    )
    consensus_pass = record.get("fabric_consensus_pass")
    divergence = _num(record.get("fabric_quote_divergence_pct"), 0.0)

    if independent_sources < max(1, int(require_independent_sources)):
        blockers.append("v11_independent_source_quorum_not_met")
    if consensus_pass is False:
        blockers.append("v11_cross_provider_quote_conflict")
    if not execution.get("execution_ready"):
        blockers.append("v11_execution_quote_not_ready")

    approved = bool(omega.get("approved")) and bool(execution.get("execution_ready")) and not blockers

    return {
        "version": "OMEGA_V11",
        "state": "CONFIRMED" if approved else "NO_TRADE",
        "approved": approved,
        "telegram_eligible": approved,
        "independent_sources": independent_sources,
        "quote_divergence_pct": round(divergence, 6),
        "consensus_pass": consensus_pass is not False,
        "omega": omega,
        "execution": execution,
        "blockers": sorted(set(str(item) for item in blockers if item)),
        "policy": (
            "V11 is fail-closed: a production alert requires the Omega evidence "
            "quorum, a fresh executable two-sided quote, and independent-source "
            "confirmation. Research rows remain visible but cannot alert."
        ),
    }


def apply_v11_gate(
    signals: list[dict[str, Any]],
    *,
    free_threshold: float = 87.0,
    max_quote_age_seconds: float = 120.0,
    require_independent_sources: int = 2,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in signals:
        row = dict(raw)
        decision = evaluate_v11_signal(
            row,
            free_threshold=free_threshold,
            max_quote_age_seconds=max_quote_age_seconds,
            require_independent_sources=require_independent_sources,
        )
        row["v11_decision"] = decision
        row["telegram_eligible"] = bool(decision["approved"])
        output.append(row)
    return output
