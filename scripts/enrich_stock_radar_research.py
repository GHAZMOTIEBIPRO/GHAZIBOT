from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.adaptive_learning import load_learning_model
from options_radar.explosion_cause import classify_explosion_cause, manipulation_risk
from options_radar.durable_stock_state import restore_missing_durable_stock_state
from options_radar.market_regime import MarketRegimeEngine
from options_radar.radar_health import assess_stock_health
from options_radar.settings import Settings
from options_radar.stock_decision import build_stock_decision
from options_radar.stock_event_outcomes import EventLevelStockOutcomeTracker

DEFAULT_PAYLOAD = Path("public/data/stocks_latest.json")
DEFAULT_LEARNING = Path(os.getenv("ADAPTIVE_LEARNING_PATH", "data/live/adaptive_learning.json"))
DEFAULT_OUTCOMES = Path(os.getenv("STOCK_OUTCOME_PATH", "data/live/stock_outcomes.json"))
DEFAULT_FAST_STATE = Path(os.getenv("FAST_MARKET_STATE_PATH", "data/live/fast_market_state.json"))


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




def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _fast_state() -> dict[str, dict[str, Any]]:
    payload = _load(DEFAULT_FAST_STATE)
    rows = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    return {
        str(symbol).upper(): row
        for symbol, row in rows.items()
        if isinstance(row, dict)
    }


def _cluster(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    intelligence = payload.get("catalyst_intelligence")
    if not isinstance(intelligence, dict):
        return {}
    by_symbol = intelligence.get("by_symbol")
    if not isinstance(by_symbol, dict):
        return {}
    value = by_symbol.get(symbol)
    return value if isinstance(value, dict) else {}


def _explosion_dimensions(
    row: dict[str, Any],
    cluster: dict[str, Any],
    memory: dict[str, Any],
) -> dict[str, float]:
    cause = row.get("cause") if isinstance(row.get("cause"), dict) else {}
    catalyst = max(
        _number(cluster.get("catalyst_quality")),
        _number(cluster.get("materiality")),
        72.0 if cause.get("official_confirmed") is True else 0.0,
        50.0 if cause.get("status") not in {None, "", "NO_PRIMARY_CAUSE_PROVEN"} else 0.0,
    )
    participation = _bounded(
        _number(row.get("turnover_score")) * 0.25
        + _number(row.get("volume_score")) * 0.20
        + _number(memory.get("anomaly")) * 0.30
        + _number(memory.get("acceleration")) * 0.25
    )
    earlyness = _number(memory.get("earlyness"), _number(row.get("move_score"), 45.0))
    price_structure = _bounded(
        earlyness * 0.58
        + _number(row.get("move_score"), 45.0) * 0.42
    )
    return {
        "catalyst": round(_bounded(catalyst), 2),
        "participation": round(participation, 2),
        "supply_structure": round(_bounded(_number(row.get("supply_score"), 45.0)), 2),
        "price_structure": round(price_structure, 2),
        # The stock path intentionally stays independent of option evidence.
        "options_structure": 0.0,
        "risk_penalty": round(_bounded(_number(memory.get("risk_penalty"))), 2),
    }


def _alert_stage(stage: str) -> str:
    normalized = str(stage or "").upper()
    if normalized == "PRESSURE_BUILDING":
        return "WATCH"
    if normalized in {"IGNITION", "EXPLOSION"}:
        return "CONFIRMED"
    if normalized == "EXTENDED":
        return "NO_CHASE"
    return "NONE"


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
    fast_state = _fast_state()
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
        symbol = str(row.get("symbol") or "").upper()
        memory = fast_state.get(symbol, {})
        cluster = _cluster(payload, symbol)
        dimensions = _explosion_dimensions(row, cluster, memory)
        explosion = classify_explosion_cause(row, cluster, dimensions)
        manipulation = manipulation_risk(row, cluster, explosion)
        row["institutional_memory"] = {
            key: memory.get(key)
            for key in ("confidence", "earlyness", "anomaly", "acceleration", "risk_penalty", "send_priority")
            if memory.get(key) is not None
        }
        row["explosion_dimensions"] = dimensions
        row["explosion_cause"] = explosion
        row["manipulation_risk"] = manipulation
        row["alert_stage"] = _alert_stage(str(row.get("stage") or ""))

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
    payload["summary"]["watch_candidates"] = sum(row.get("alert_stage") == "WATCH" for row in stocks)
    payload["summary"]["confirmed_candidates"] = sum(row.get("alert_stage") == "CONFIRMED" for row in stocks)
    payload["summary"]["multi_factor_explosions"] = sum(
        (row.get("explosion_cause") or {}).get("primary") == "MULTI_FACTOR_EXPLOSION"
        for row in stocks
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
            "explosion_cause_is_explanatory_not_proven_causation": True,
            "manipulation_risk_is_research_flag_not_accusation": True,
            "stock_path_uses_options_structure": False,
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
