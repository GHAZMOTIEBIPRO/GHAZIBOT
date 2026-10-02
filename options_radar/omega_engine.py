from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .official_catalyst_intelligence import build_catalyst_intelligence
from .omega_observability import apply_observability
from .omega_target_learning import load_target_calibration
from .omega_target_learning import _load as load_target_state
from .omega_opportunity import build_omega_opportunities
from .omega_validation import build_validation_status


def apply_omega(payload: dict[str, Any]) -> dict[str, Any]:
    """Idempotently enrich an exported payload with Ω research layers."""

    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    catalysts = payload.get("catalysts") if isinstance(payload.get("catalysts"), list) else []
    catalyst_intelligence = build_catalyst_intelligence(catalysts, stocks)
    target_calibration = load_target_calibration("data/live/omega_target_calibration.json")
    target_state = load_target_state("data/live/omega_target_state.json", {})
    opportunities = build_omega_opportunities(
        payload,
        catalyst_intelligence,
        target_calibration=target_calibration,
        target_state=target_state,
    )
    validation = build_validation_status(payload)

    status_path = Path("data/cache/sec_incremental_status.json")
    if status_path.exists():
        try:
            payload["sec_incremental_metrics"] = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload["sec_incremental_metrics"] = {"status": "unreadable"}

    payload["omega"] = {
        "version": "2026.10-omega-v13-target-learning",
        "research_status": "RANKING_ONLY",
        "probability_calibrated": opportunities["probability_calibrated"],
        "target_calibration": {
            "ready": opportunities["probability_calibrated"],
            "matured_t1_sample": opportunities["target_calibration_sample"],
            "minimum_global_sample": int(target_calibration.get("minimum_global_sample") or 100)
            if isinstance(target_calibration, dict)
            else 100,
            "similar_case_library_signals": len(
                target_state.get("signals", {})
                if isinstance(target_state, dict) and isinstance(target_state.get("signals"), dict)
                else {}
            ),
        },
        "catalyst_intelligence": catalyst_intelligence,
        "omega_day": opportunities["omega_day"],
        "omega_swing": opportunities["omega_swing"],
        "explosion_radar": opportunities["explosion_radar"],
        "target_maps": opportunities["target_maps"],
        "opportunities": opportunities["all_ranked"],
        "summary": opportunities["summary"],
        "validation": validation,
    }

    summary = payload.setdefault("summary", {})
    summary["omega_ranked"] = opportunities["summary"]["ranked"]
    summary["omega_day_opportunities"] = opportunities["summary"]["day_opportunities"]
    summary["omega_swing_opportunities"] = opportunities["summary"]["swing_opportunities"]
    summary["omega_upside_candidates"] = opportunities["summary"]["upside_candidates"]
    summary["omega_downside_candidates"] = opportunities["summary"]["downside_candidates"]
    summary["omega_tier_a_plus"] = opportunities["summary"]["tier_a_plus"]
    summary["omega_tier_a"] = opportunities["summary"]["tier_a"]
    summary["omega_tier_b"] = opportunities["summary"]["tier_b"]
    summary["omega_rejected"] = opportunities["summary"]["rejected"]
    summary["catalyst_event_clusters"] = catalyst_intelligence["event_clusters"]
    summary["catalyst_duplicates_collapsed"] = catalyst_intelligence["duplicates_collapsed"]
    summary["official_confirmed_catalysts"] = catalyst_intelligence.get("official_confirmed_clusters", 0)
    summary["attention_only_catalysts"] = catalyst_intelligence.get("attention_only_clusters", 0)

    apply_observability(payload)
    return payload
