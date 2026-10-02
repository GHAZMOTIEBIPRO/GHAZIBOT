from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from options_radar.hybrid_fetcher import DataFetcher


GRID = (
    ("call", 100.0, 80.0, 7, 0.20),
    ("call", 100.0, 100.0, 30, 0.30),
    ("call", 100.0, 120.0, 60, 0.55),
    ("put", 100.0, 80.0, 14, 0.45),
    ("put", 100.0, 100.0, 45, 0.25),
    ("put", 100.0, 120.0, 90, 0.60),
)

TOLERANCES = {
    "delta": 2e-6,
    "gamma": 2e-6,
    "theta": 2e-6,
    "vega": 2e-6,
}


def _reference(side: str, spot: float, strike: float, years: float, rate: float, iv: float):
    flag = "c" if side == "call" else "p"
    try:
        from py_vollib_vectorized import get_all_greeks

        values = get_all_greeks(
            flag,
            spot,
            strike,
            years,
            rate,
            iv,
            model="black_scholes",
            return_as="dict",
        )
        return {
            key: float(values[key][0] if hasattr(values[key], "__len__") else values[key])
            for key in ("delta", "gamma", "theta", "vega")
        }, "py_vollib_vectorized"
    except Exception:
        from py_vollib.black_scholes.greeks.analytical import delta, gamma, theta, vega

        return {
            "delta": float(delta(flag, spot, strike, years, rate, iv)),
            "gamma": float(gamma(flag, spot, strike, years, rate, iv)),
            "theta": float(theta(flag, spot, strike, years, rate, iv)),
            "vega": float(vega(flag, spot, strike, years, rate, iv)),
        }, "py_vollib"


def validate() -> dict:
    rate = 0.043
    rows = []
    failures = []
    reference_engine = None
    for side, spot, strike, dte, iv in GRID:
        years = dte / 365.0
        ours = DataFetcher.black_scholes_greeks(spot, strike, years, rate, iv, side)
        reference, engine = _reference(side, spot, strike, years, rate, iv)
        reference_engine = engine
        differences = {
            key: abs(float(ours[key]) - float(reference[key]))
            for key in TOLERANCES
        }
        passed = all(differences[key] <= TOLERANCES[key] for key in TOLERANCES)
        row = {
            "side": side,
            "spot": spot,
            "strike": strike,
            "dte": dte,
            "iv": iv,
            "ours": ours,
            "reference": reference,
            "absolute_difference": differences,
            "passed": passed,
        }
        rows.append(row)
        if not passed:
            failures.append(row)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validator": reference_engine,
        "license": "MIT",
        "project_refs": [
            "vollib/py_vollib",
            "marcdemers/py_vollib_vectorized",
        ],
        "grid_size": len(rows),
        "passed": not failures,
        "failure_count": len(failures),
        "tolerances": TOLERANCES,
        "rows": rows,
        "decision_authority": False,
        "mode": "SHADOW_VALIDATION",
    }


def main() -> None:
    payload = validate()
    path = Path("public/data/open_source_greeks_validation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Open-source Greeks validation: passed={payload['passed']} "
        f"grid={payload['grid_size']} validator={payload['validator']}"
    )
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
