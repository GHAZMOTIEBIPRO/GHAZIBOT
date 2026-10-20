"""Decide whether a market-data workflow has a permitted source to run on.

Standard library only; options_radar.source_permissions is loaded by file
path so this runs before dependencies are installed. Credentials are seen
only as HAS_<NAME>=true/false booleans set by the workflow, never values.

A job whose only inputs are closed sources is skipped with an explicit
notice instead of failing on empty data every cycle.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ghazi_source_permissions_gate",
                                               ROOT / "options_radar" / "source_permissions.py")
permissions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(permissions)

RIGHTS_PATH = ROOT / "data" / "source_rights.json"
# Which provider each credential belongs to, for the rights matrix.
KEY_PROVIDER = {
    "TIINGO_API_KEY": "tiingo", "FINNHUB_API_KEY": "finnhub", "TRADIER_TOKEN": "tradier",
    "ALPACA_API_KEY": "alpaca", "TWELVE_DATA_API_KEY": "twelve_data", "POLYGON_API_KEY": "massive_polygon",
    "ALPHA_VANTAGE_API_KEY": "alpha_vantage", "MARKETDATA_TOKEN": "marketdata_app",
}
# Account APIs the existing adapters can use for each kind of input. A key
# alone is not permission: the provider's official terms (data/source_rights.json)
# must not restrict automated access or internal analysis, and rights the
# terms leave UNKNOWN count only after the owner confirms the plan's terms in
# the DATA_TERMS_CONFIRMED variable. Public display is a separate question
# (options_radar/public_guard.py).
ACCOUNT_KEYS = {
    "price": ("TIINGO_API_KEY", "FINNHUB_API_KEY", "TRADIER_TOKEN", "ALPACA_API_KEY",
              "TWELVE_DATA_API_KEY", "POLYGON_API_KEY", "ALPHA_VANTAGE_API_KEY"),
    "options": ("TRADIER_TOKEN", "MARKETDATA_TOKEN", "FINNHUB_API_KEY", "ALPACA_API_KEY"),
    "discovery": (),
}
GATED_SOURCE = {"price": "yahoo", "options": "yahoo", "discovery": "nasdaq_web"}


def _has(name: str) -> bool:
    return os.getenv(f"HAS_{name}", "").strip().lower() == "true"


def _rights() -> dict:
    try:
        return json.loads(RIGHTS_PATH.read_text(encoding="utf-8")).get("providers", {})
    except (OSError, ValueError):
        return {}


def key_usable(key: str, rights: dict | None = None) -> bool:
    """A configured key counts only when the provider's terms allow our use."""
    if not _has(key):
        return False
    provider = KEY_PROVIDER.get(key)
    entry = (rights if rights is not None else _rights()).get(provider or "", {})
    statuses = [str((entry.get("rights", {}).get(right) or {}).get("status") or "UNKNOWN")
                for right in ("automated_access", "internal_analysis")]
    if "RESTRICTED" in statuses or not entry:
        return False
    if all(status == "VERIFIED" for status in statuses):
        return True
    confirmed = {x.strip() for x in os.getenv("DATA_TERMS_CONFIRMED", "").split(",") if x.strip()}
    return provider in confirmed


def evaluate(requirements: list[str]) -> tuple[bool, list[str]]:
    missing = []
    rights = _rights()
    for need in requirements:
        if permissions.allowed(GATED_SOURCE[need]) or any(key_usable(key, rights) for key in ACCOUNT_KEYS[need]):
            continue
        missing.append(need)
    return not missing, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require", required=True, help="comma list of price, options, discovery")
    args = parser.parse_args()
    needs = [x.strip() for x in args.require.split(",") if x.strip()]
    unknown = [x for x in needs if x not in GATED_SOURCE]
    if unknown:
        raise SystemExit(f"unknown requirement: {unknown}")
    usable, missing = evaluate(needs)
    reason = "" if usable else (
        "SOURCE_TERMS_BLOCKED: no permitted source for " + ", ".join(missing) +
        " (Yahoo/Nasdaq.com automated access not permitted and no account API configured); scan skipped")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"usable={'true' if usable else 'false'}\n")
            handle.write(f"reason={reason}\n")
    if usable:
        print("Permitted source available for:", ", ".join(needs))
    else:
        print(f"::notice::{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
