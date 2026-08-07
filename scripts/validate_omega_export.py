from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.omega_engine import apply_omega


REQUIRED_DIMENSIONS = {
    "catalyst",
    "participation",
    "supply_structure",
    "price_structure",
    "options_structure",
    "risk_penalty",
}


def validate_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    omega = payload.get("omega")
    if not isinstance(omega, dict):
        return ["missing omega object"]

    validation = omega.get("validation")
    if not isinstance(validation, dict):
        errors.append("missing omega.validation")
    elif validation.get("edge_status") == "EDGE PROVEN":
        errors.append("forbidden unqualified EDGE PROVEN claim")

    opportunities = omega.get("opportunities")
    if not isinstance(opportunities, list):
        errors.append("omega.opportunities must be a list")
        opportunities = []

    for index, row in enumerate(opportunities):
        if row.get("probability_of_profit") is not None:
            errors.append(f"opportunity[{index}] exposes uncalibrated probability")
        if set((row.get("dimensions") or {}).keys()) != REQUIRED_DIMENSIONS:
            errors.append(f"opportunity[{index}] missing separated explosion dimensions")
        if row.get("opportunity_tier") in {"A+", "A"} and not row.get("tradable_contract"):
            errors.append(f"opportunity[{index}] Tier A without tradable contract")
        target = row.get("target_map") or {}
        for key in ("entry", "invalidation", "t1", "t2", "t3"):
            if key not in target:
                errors.append(f"opportunity[{index}] target map missing {key}")

    intelligence = omega.get("catalyst_intelligence")
    if not isinstance(intelligence, dict):
        errors.append("missing catalyst intelligence")
    else:
        for index, cluster in enumerate(intelligence.get("clusters", [])):
            for key in (
                "category",
                "directional_bias",
                "materiality",
                "primary_source",
                "confidence",
                "dilution_risk",
                "confirmation_count",
                "reaction_state",
            ):
                if key not in cluster:
                    errors.append(f"catalyst cluster[{index}] missing {key}")
            firewall = cluster.get("causal_firewall") or {}
            if firewall.get("probability_of_profit") is not None:
                errors.append(f"catalyst cluster[{index}] violates causal firewall")

    expiry = payload.get("expiry_radar") if isinstance(payload.get("expiry_radar"), dict) else {}
    contracts = expiry.get("contracts") if isinstance(expiry.get("contracts"), list) else []
    for index, contract in enumerate(contracts):
        if "dte" not in contract:
            errors.append(f"expiry contract[{index}] missing DTE")
        if not str(contract.get("expiry_family") or "").strip():
            errors.append(f"expiry contract[{index}] missing expiry_family")

    health = payload.get("health")
    data_status = payload.get("data_status")
    if not isinstance(health, dict):
        errors.append("missing health object")
    if not isinstance(data_status, dict):
        errors.append("missing data_status object")
    return errors


def validate_ui(root: Path) -> list[str]:
    errors: list[str] = []
    index = (root / "public/index.html").read_text(encoding="utf-8")
    omega_js = (root / "public/omega.js").read_text(encoding="utf-8")
    for marker in (
        'data-tab="omega"',
        'id="tab-omega"',
        'id="omega-day-grid"',
        'id="omega-swing-grid"',
        'id="omega-upside-grid"',
        'id="omega-downside-grid"',
        'id="omega-catalyst-grid"',
        'src="./omega.js',
    ):
        if marker not in index:
            errors.append(f"UI missing {marker}")
    for forbidden in ("عقود أسبوعية 3–10 DTE", "عقود شهرية 11–45 DTE"):
        if forbidden in index:
            errors.append(f"UI still contains DTE-as-family label: {forbidden}")
    if "probability_of_profit = null" not in omega_js:
        errors.append("Omega UI does not expose ranking-not-probability guard")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="public/data/latest.json")
    parser.add_argument("--apply-in-memory", action="store_true")
    args = parser.parse_args()

    path = Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if args.apply_in_memory or not isinstance(payload.get("omega"), dict):
        apply_omega(payload)

    errors = validate_payload(payload) + validate_ui(ROOT)
    if errors:
        print("Omega validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "Omega validation OK: "
        f"{len(payload.get('omega', {}).get('opportunities', []))} ranked opportunities, "
        f"{len(payload.get('omega', {}).get('catalyst_intelligence', {}).get('clusters', []))} catalyst clusters"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
