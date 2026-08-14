from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from options_radar.provider_readiness import assess_provider_readiness
from options_radar.runtime_hardening import install_options_radar_hardening
from options_radar.settings import Settings

from scripts import run_options_radar_independent as base


def _quarantine_research_contracts(payload: dict, readiness: dict) -> None:
    if readiness.get("production_quote_ready") is True:
        payload.setdefault("summary", {})["production_alerts_blocked"] = False
        return

    contracts = [row for row in payload.get("contracts", []) if isinstance(row, dict)]
    top_calls = [row for row in payload.get("top_calls", []) if isinstance(row, dict)]
    top_puts = [row for row in payload.get("top_puts", []) if isinstance(row, dict)]
    summary = payload.setdefault("summary", {})

    payload["research_contracts"] = contracts
    payload["research_top_calls"] = top_calls
    payload["research_top_puts"] = top_puts
    payload["contracts"] = []
    payload["top_calls"] = []
    payload["top_puts"] = []

    summary["research_contracts_selected"] = len(contracts)
    summary["research_calls_selected"] = len(top_calls)
    summary["research_puts_selected"] = len(top_puts)
    summary["contracts_selected"] = 0
    summary["calls_selected"] = 0
    summary["puts_selected"] = 0
    summary["production_alerts_blocked"] = True
    summary["production_block_reason"] = str(readiness.get("status") or "PROVIDER_NOT_READY")

    payload.setdefault("flow_policy", {}).update(
        {
            "fallback_contracts_can_enter_production_alerts": False,
            "fallback_contracts_can_enter_cross_confirmation": False,
            "fallback_contracts_remain_available_for_shadow_research": True,
        }
    )
    payload.setdefault("limitations", []).append(
        "Provider readiness is not production-grade; selected contracts were quarantined into research_contracts and removed from production contracts."
    )


def run(
    *,
    universe_path: str | Path = base.DEFAULT_INPUT,
    output_path: str | Path = base.DEFAULT_OUTPUT,
    max_symbols: int = 80,
    top_per_side: int = 15,
) -> dict:
    install_options_radar_hardening()
    payload = base.run(
        universe_path=universe_path,
        output_path=output_path,
        max_symbols=max_symbols,
        top_per_side=top_per_side,
    )
    settings = Settings()
    readiness = assess_provider_readiness(
        payload.get("provider_audit"),
        tradier_base_url=settings.tradier_base_url,
    ).as_dict()
    payload["provider_readiness"] = readiness
    payload.setdefault("summary", {})["provider_readiness"] = readiness["status"]
    payload["summary"]["production_quote_ready"] = readiness["production_quote_ready"]
    payload["summary"]["production_flow_ready"] = readiness["production_flow_ready"]
    _quarantine_research_contracts(payload, readiness)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hardened independent BLACK BOX options radar")
    parser.add_argument("--universe", default=str(base.DEFAULT_INPUT))
    parser.add_argument("--output", default=str(base.DEFAULT_OUTPUT))
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=int(os.getenv("OPTIONS_INDEPENDENT_MAX_SYMBOLS", "80")),
    )
    parser.add_argument(
        "--top-per-side",
        type=int,
        default=int(os.getenv("OPTIONS_INDEPENDENT_TOP_PER_SIDE", "15")),
    )
    args = parser.parse_args()
    payload = run(
        universe_path=args.universe,
        output_path=args.output,
        max_symbols=args.max_symbols,
        top_per_side=args.top_per_side,
    )
    summary = payload.get("summary") or {}
    print(
        "Hardened options radar: "
        f"symbols={summary.get('symbols_scanned', 0)} "
        f"calls={summary.get('calls_selected', 0)} "
        f"puts={summary.get('puts_selected', 0)} "
        f"research={summary.get('research_contracts_selected', 0)} "
        f"provider_readiness={summary.get('provider_readiness', 'UNKNOWN')} "
        f"blocked={summary.get('production_alerts_blocked', False)}"
    )


if __name__ == "__main__":
    main()
