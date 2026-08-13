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
from options_radar.radar_health import assess_options_health
from options_radar.settings import Settings

DEFAULT_PAYLOAD = Path("public/data/options_latest.json")
DEFAULT_LEARNING = Path(os.getenv("ADAPTIVE_LEARNING_PATH", "data/live/adaptive_learning.json"))


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
    if payload.get("path") != "options":
        raise RuntimeError("Expected independent options payload")

    settings = Settings()
    settings.validate()
    learning = load_learning_model(DEFAULT_LEARNING)
    regime = str((payload.get("summary") or {}).get("market_regime") or "unknown")
    contracts = [row for row in payload.get("contracts", []) if isinstance(row, dict)]
    for row in contracts:
        row.setdefault("market_regime", regime)
        row["shadow_analysis"] = {
            **apply_options_learning(row, learning),
            "live_alert_eligibility_changed": False,
            "mode": "SHADOW_ONLY",
        }

    by_contract = {str(row.get("contract_symbol") or ""): row for row in contracts}
    for key in ("top_calls", "top_puts"):
        enriched: list[dict[str, Any]] = []
        for raw in payload.get(key, []):
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            contract = str(row.get("contract_symbol") or "")
            if contract in by_contract:
                row.update(by_contract[contract])
            enriched.append(row)
        payload[key] = enriched
    payload["contracts"] = contracts

    generated_at = datetime.now(timezone.utc)
    frame = pd.DataFrame(contracts)
    recorded = SignalJournal(
        settings.signal_journal_path,
        settings.outcome_path,
        settings.model_version,
        settings=settings,
    ).record(frame, generated_at)

    payload["adaptive_learning"] = learning.get("options", {})
    payload.setdefault("summary", {})["shadow_learning_ready"] = bool((learning.get("options") or {}).get("ready"))
    payload["summary"]["signals_recorded_this_run"] = recorded
    payload.setdefault("flow_policy", {}).update(
        {
            "adaptive_learning_mode": "shadow_only",
            "adaptive_learning_changes_live_alerts": False,
            "trade_quote_adapter_ready": True,
            "licensed_trade_quote_feed_configured": False,
        }
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
        f"learning={(payload.get('summary') or {}).get('shadow_learning_ready', False)} "
        f"health={(payload.get('health') or {}).get('status', 'UNKNOWN')}"
    )


if __name__ == "__main__":
    main()
