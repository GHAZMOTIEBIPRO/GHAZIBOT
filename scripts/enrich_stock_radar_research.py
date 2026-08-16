from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.adaptive_learning import load_learning_model
from options_radar.durable_stock_state import restore_missing_durable_stock_state
from options_radar.market_regime import MarketRegimeEngine
from options_radar.radar_health import assess_stock_health
from options_radar.settings import Settings
from options_radar.stock_decision import build_stock_decision
from options_radar.stock_event_outcomes import EventLevelStockOutcomeTracker

DEFAULT_PAYLOAD = Path("public/data/stocks_latest.json")
DEFAULT_LEARNING = Path(os.getenv("ADAPTIVE_LEARNING_PATH", "data/live/adaptive_learning.json"))
DEFAULT_OUTCOMES = Path(os.getenv("STOCK_OUTCOME_PATH", "data/live/stock_outcomes.json"))


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def enrich(payload_path: str | Path = DEFAULT_PAYLOAD) -> dict[str, Any]:
    destination = Path(payload_path)
    payload = _load(destination)
    if payload.get("path") != "stocks":
        raise RuntimeError("Expected independent stock payload")

    errors = payload.setdefault("errors", [])
    durable = restore_missing_durable_stock_state()
    if durable.error:
        errors.append(f"durable_stock_state: {durable.error}")

    settings = Settings()
    settings.validate()
    try:
        regime = MarketRegimeEngine(settings).evaluate()
        regime_label = regime.label
        regime_detail = regime.to_dict()
        call_adjustment = float(regime.call_score_adjustment)
        put_adjustment = float(regime.put_score_adjustment)
    except Exception as exc:
        regime_label = "unknown"
        regime_detail = {}
        call_adjustment = 0.0
        put_adjustment = 0.0
        errors.append(f"market_regime: {type(exc).__name__}: {exc}")

    learning = load_learning_model(DEFAULT_LEARNING)
    stocks = [row for row in payload.get("stocks", []) if isinstance(row, dict)]
    for row in stocks:
        row["market_regime"] = regime_label
        move = float(row.get("move_pct") or 0.0)
        overlay = build_stock_decision(
            row,
            market_regime_adjustment=put_adjustment if move < 0 else call_adjustment,
            learning_model=learning,
        ).as_dict()
        row["shadow_analysis"] = {
            **overlay,
            "live_alert_eligibility_changed": False,
            "mode": "SHADOW_ONLY",
        }

    outcomes = EventLevelStockOutcomeTracker(DEFAULT_OUTCOMES).update(
        stocks,
        now=datetime.now(timezone.utc),
        market_regime=regime_label,
    )
    payload["market_regime"] = regime_detail
    payload["adaptive_learning"] = learning.get("stock", {})
    payload["stock_outcome_summary"] = outcomes.get("summary", {})
    payload["stock_event_dedup"] = outcomes.get("event_dedup", {})
    payload["durable_stock_state"] = {
        "attempted": durable.attempted,
        "branch_available": durable.branch_available,
        "restored": list(durable.restored),
        "preserved_local": list(durable.preserved_local),
    }
    payload.setdefault("summary", {})["market_regime"] = regime_label
    payload["summary"]["shadow_learning_ready"] = bool((learning.get("stock") or {}).get("ready"))
    payload["summary"]["event_samples_after_dedup"] = int(
        (outcomes.get("event_dedup") or {}).get("samples_after_dedup", 0) or 0
    )
    payload.setdefault("policy", {}).update(
        {
            "adaptive_learning_mode": "shadow_only",
            "adaptive_learning_changes_live_alerts": False,
            "raw_score_preserved": True,
            "late_move_risk_is_measured": True,
            "learning_sample_unit": "event_not_stage_snapshot",
            "same_symbol_direction_reentry_gap_minutes": 240,
            "durable_stock_state_is_fallback_only": True,
        }
    )
    payload["health"] = assess_stock_health(payload)
    _write(destination, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich stock radar with research-only learning evidence")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    args = parser.parse_args()
    payload = enrich(args.payload)
    print(
        "Stock research enrichment: "
        f"regime={(payload.get('summary') or {}).get('market_regime', 'unknown')} "
        f"health={(payload.get('health') or {}).get('status', 'UNKNOWN')} "
        f"tracked={(payload.get('stock_outcome_summary') or {}).get('tracked', 0)} "
        f"events={(payload.get('summary') or {}).get('event_samples_after_dedup', 0)}"
    )


if __name__ == "__main__":
    main()
