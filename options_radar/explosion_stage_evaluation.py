"""Measured quality of Explosion Hunter stages on matured audit records.

Research only. Three different questions are kept apart:
- direction: did price reach the signal's own follow-through target before
  its failure threshold (audit success vs failed)?
- volatility: did price move by the target size in *either* direction? A
  large move is not evidence that a long signal was right.
- economics: threshold payoff per decisive signal after an explicit cost
  assumption. Stages use different targets and stops, so raw hit rates are
  not comparable; the break-even hit rate is published with each stage.

Precision/recall treat "audit success" as the positive class. Recall is the
share of all observed successes that a stage captured. The time split uses
signal session dates only (earlier sessions vs later sessions).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any

SCHEMA = "ghazi.explosion_stage_evaluation.v1"
STAGES = ("PRESSURE_BUILDING", "IGNITION", "EXPLOSION")
EARLY_SHARE = 0.6
MIN_DECISIVE_FOR_VERDICT = 30


def round_trip_cost_pct(entry_price: float | None) -> float:
    """Documented assumption for spread + slippage + fees on U.S. stocks."""
    if entry_price is None or entry_price <= 0:
        return 1.5
    if entry_price < 2:
        return 1.5
    if entry_price < 10:
        return 0.6
    return 0.2


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(centre - half, 4), round(centre + half, 4)


def _session(row: dict[str, Any]) -> str:
    return str(row.get("signal_session_date") or str(row.get("signal_time") or "")[:10])


def _stats(rows: list[dict[str, Any]], total_successes: int, pooled_rate: float | None) -> dict[str, Any]:
    decisive = [r for r in rows if r.get("audit_status") in {"success", "failed"}]
    wins = sum(r["audit_status"] == "success" for r in decisive)
    n = len(decisive)
    precision = wins / n if n else None
    targets = [_num(r.get("follow_through_target_pct")) for r in decisive]
    stops = [_num(r.get("failure_threshold_pct")) for r in decisive]
    gross, net = [], []
    for row, target, stop in zip(decisive, targets, stops):
        if target is None or stop is None:
            continue
        payoff = target if row["audit_status"] == "success" else -abs(stop)
        gross.append(payoff)
        net.append(payoff - round_trip_cost_pct(_num(row.get("entry_price"))))
    breakeven = None
    if targets and stops and all(t is not None for t in targets) and all(s is not None for s in stops):
        mean_t, mean_s = sum(targets) / len(targets), sum(abs(s) for s in stops) / len(stops)
        breakeven = round(mean_s / (mean_t + mean_s), 4)
    moved = 0
    measured_moves = 0
    for row in rows:
        mfe, mae = _num(row.get("audit_mfe_pct")), _num(row.get("audit_mae_pct"))
        target = _num(row.get("follow_through_target_pct"))
        if mfe is None or mae is None or target is None:
            continue
        measured_moves += 1
        moved += mfe >= target or mae <= -target
    return {
        "signals": len(rows),
        "decisive": n,
        "successes": wins,
        "pending": sum(r.get("audit_status") == "pending" for r in rows),
        "non_decisive": sum(r.get("audit_status") == "non_decisive" for r in rows),
        "precision_direction": round(precision, 4) if precision is not None else None,
        "precision_ci95": wilson(wins, n),
        "lift_vs_pooled_baseline": (round(precision - pooled_rate, 4)
                                    if precision is not None and pooled_rate is not None else None),
        "breakeven_hit_rate": breakeven,
        "recall_share_of_all_successes": round(wins / total_successes, 4) if total_successes else None,
        "expectancy_gross_pct": round(sum(gross) / len(gross), 3) if gross else None,
        "expectancy_net_pct": round(sum(net) / len(net), 3) if net else None,
        "big_move_any_direction_rate": round(moved / measured_moves, 4) if measured_moves else None,
        "big_move_measured": measured_moves,
        "verdict_sample_sufficient": n >= MIN_DECISIVE_FOR_VERDICT,
    }


def evaluate(audit: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    rows = [r for r in records.values() if isinstance(r, dict)
            and r.get("signal_session_valid") is not False
            and str(r.get("entry_stage") or "").upper() in STAGES]
    decisive = [r for r in rows if r.get("audit_status") in {"success", "failed"}]
    total_successes = sum(r["audit_status"] == "success" for r in decisive)
    pooled = total_successes / len(decisive) if decisive else None

    sessions = sorted({_session(r) for r in rows if _session(r)})
    cut = sessions[int(len(sessions) * EARLY_SHARE)] if len(sessions) >= 5 else None
    by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_stage[str(row["entry_stage"]).upper()].append(row)

    stages = {}
    for stage in STAGES:
        group = by_stage.get(stage, [])
        entry = _stats(group, total_successes, pooled)
        if cut is not None:
            early = [r for r in group if _session(r) < cut]
            late = [r for r in group if _session(r) >= cut]
            e_stats, l_stats = _stats(early, total_successes, pooled), _stats(late, total_successes, pooled)
            entry["time_split"] = {
                "early_sessions_before": cut,
                "early": {k: e_stats[k] for k in ("decisive", "precision_direction", "expectancy_net_pct")},
                "late": {k: l_stats[k] for k in ("decisive", "precision_direction", "expectancy_net_pct")},
            }
        stages[stage] = entry

    captured = [r for r in rows if isinstance(r.get("entry_features_v1"), dict) and r["entry_features_v1"]]
    time_rvol = [r for r in rows if (r.get("time_normalized_rvol_entry") or {}).get("available") is True]
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "source_audit_updated_at": audit.get("updated_at"),
        "population": {
            "eligible_stage_signals": len(rows),
            "decisive": len(decisive),
            "sessions": len(sessions),
            "pooled_direction_baseline": round(pooled, 4) if pooled is not None else None,
        },
        "stages": stages,
        "feature_capture": {
            "records_with_entry_features_v1": len(captured),
            "records_with_time_normalized_rvol": len(time_rvol),
            "gating_hypotheses_testable": False,
            "reason": "stage rule changes are evaluated only after enough decisive records carry "
                      "signal-time features, on later sessions than those used to propose them",
        },
        "cost_model": {
            "round_trip_pct_by_entry_price": {"<2": 1.5, "2-10": 0.6, ">=10": 0.2},
            "assumption_not_measured_fills": True,
        },
        "definitions": {
            "precision_direction": "audit success / decisive (own target before own stop)",
            "big_move_any_direction_rate": "share with MFE >= target or MAE <= -target; not direction accuracy",
            "expectancy": "mean threshold payoff per decisive signal; non-decisive and pending excluded",
        },
        "research_only": True,
        "decision_authority": False,
        "score_is_probability": False,
        "live_rules_changed": False,
    }
