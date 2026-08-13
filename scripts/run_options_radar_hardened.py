from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from options_radar.provider_readiness import assess_provider_readiness
from options_radar.runtime_hardening import install_options_radar_hardening
from options_radar.settings import Settings

from scripts import run_options_radar_independent as base


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
    if not readiness["production_quote_ready"]:
        payload.setdefault("limitations", []).append(
            "Options provider readiness is FALLBACK_ONLY/DELAYED; contract output must remain research-only."
        )
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
        f"provider_readiness={summary.get('provider_readiness', 'UNKNOWN')}"
    )


if __name__ == "__main__":
    main()
