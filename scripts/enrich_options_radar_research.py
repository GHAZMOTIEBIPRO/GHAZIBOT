from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from options_radar.adaptive_learning import load_learning_model
from options_radar.adaptive_overlay import apply_options_learning
from options_radar.outcomes import SignalJournal
from options_radar.provider_readiness import assess_provider_readiness
from options_radar.radar_health import assess_options_health
from options_radar.settings import Settings

DEFAULT_PAYLOAD = Path("public/data/options_latest.json")
DEFAULT_LEARNING = Path(os.getenv("ADAPTIVE_LEARNING_PATH", "data/live/adaptive_learning.json"))
MAX_RESEARCH_SOURCE_AGE_MINUTES = 45


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


def _source_age_minutes(payload: dict[str, Any], now: datetime) -> float | None:
    text = str(payload.get("generated_at") or "").strip()
    if not text:
        return None
    try:
        generated = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return (now - generated.astimezone(timezone.utc)).total_seconds() / 60.0


def enrich(payload_path: str | Path = DEFAULT_PAYLOAD) -> dict[str, Any]:
    destination = Path(payload_path)
    payload = _load(destination)
    if payload.get("path") != "options":
        raise RuntimeError("Expected independent options payload")

    settings = Settings()
    settings.validate()
    readiness = assess_provider_readiness(
        payload.get("provider_audit"),
        tradier_base_url=settings.tradier_base_url,
    ).as_dict()
    payload["provider_readiness"] = readiness
    payload.setdefault("summary", {})["provider_readiness"] = readiness["status"]
    payload["summary"]["production_quote_ready"] = readiness["production_quote_ready"]
    payload["summary"]["production_flow_ready"] = readiness["production_flow_ready"]

    learning = load_learning_model(DEFAULT_LEARNING)
    regime = str((payload.get("summary") or {}).get("market_regime") or "unknown")
    source_contracts = payload.get("research_contracts")
    if not isinstance(source_contracts, list):
        source_contracts = payload.get("contracts", [])
    contracts = [row for row in source_contracts if isinstance(row, dict)]
    for row in contracts:
        row.setdefault("market_regime", regime)
        row["shadow_analysis"] = {
            **apply_options_learning(row, learning),
            "live_alert_eligibility_changed": False,
            "mode": "SHADOW_ONLY",
        }

    by_contract = {str(row.get("contract_symbol") or ""): row for row in contracts}
    research_mode = isinstance(payload.get("research_contracts"), list)
    top_pairs = (
        (("research_top_calls", "research_top_calls"), ("research_top_puts", "research_top_puts"))
        if research_mode
        else (("top_calls", "top_calls"), ("top_puts", "top_puts"))
    )
    for source_key, destination_key in top_pairs:
        enriched: list[dict[str, Any]] = []
        for raw in payload.get(source_key, []):
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            contract = str(row.get("contract_symbol") or "")
            if contract in by_contract:
                row.update(by_contract[contract])
            enriched.append(row)
        payload[destination_key] = enriched
    if research_mode:
        payload["research_contracts"] = contracts
    else:
        payload["contracts"] = contracts

    now = datetime.now(timezone.utc)
    source_age = _source_age_minutes(payload, now)
    source_is_fresh = source_age is not None and -2.0 <= source_age <= MAX_RESEARCH_SOURCE_AGE_MINUTES
    recorded = 0
    if source_is_fresh:
        frame = pd.DataFrame(contracts)
        recorded = SignalJournal(
            settings.signal_journal_path,
            settings.outcome_path,
            settings.model_version,
            settings=settings,
        ).record(frame, now)

    payload["adaptive_learning"] = learning.get("options", {})
    payload.setdefault("summary", {})["shadow_learning_ready"] = bool((learning.get("options") or {}).get("ready"))
    payload["summary"]["signals_recorded_this_run"] = recorded
    payload["summary"]["research_contracts_available"] = len(contracts)
    payload["summary"]["research_source_age_minutes"] = round(source_age, 2) if source_age is not None else None
    payload["summary"]["research_source_fresh"] = source_is_fresh
    payload.setdefault("flow_policy", {}).update(
        {
            "adaptive_learning_mode": "shadow_only",
            "adaptive_learning_changes_live_alerts": False,
            "trade_quote_adapter_ready": True,
            "licensed_trade_quote_feed_configured": bool(readiness["production_flow_ready"]),
            "stale_payload_can_create_new_learning_signal": False,
            "quarantined_fallback_contracts_are_research_only": True,
        }
    )
    if not readiness["production_quote_ready"]:
        payload.setdefault("limitations", []).append(
            "Provider audit is fallback-only/delayed; fallback contracts are quarantined for shadow research and cannot enter production contracts."
        )
    if not source_is_fresh:
        payload.setdefault("limitations", []).append(
            "Research enrichment saw a stale/undated source payload and deliberately recorded zero new option signals."
        )
    payload["health"] = assess_options_health(payload)
    _write(destination, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich options radar with research-only outcome evidence")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    args = parser.parse_args()
    payload = enrich(args.payload)
    print(
        "Options research enrichment: "
        f"recorded={(payload.get('summary') or {}).get('signals_recorded_this_run', 0)} "
        f"research={(payload.get('summary') or {}).get('research_contracts_available', 0)} "
        f"fresh={(payload.get('summary') or {}).get('research_source_fresh', False)} "
        f"learning={(payload.get('summary') or {}).get('shadow_learning_ready', False)} "
        f"provider={(payload.get('summary') or {}).get('provider_readiness', 'UNKNOWN')} "
        f"health={(payload.get('health') or {}).get('status', 'UNKNOWN')}"
    )


if __name__ == "__main__":
    main()
