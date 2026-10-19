"""Publish the existing 7k-symbol structural scan as a bounded watch catalog.

No network, no price/option claims, no synthetic observations. Source snapshot
provenance and age survive every automated republish to bot-state.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
MAX_ROWS = 60
MAX_AGE_HOURS = 7 * 24
MAX_INPUT_BYTES = 350_000
EXCLUDED = {"SPX", "NDX", "DJI", "VIX", "SPY", "QQQ", "IWM", "DIA"}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def parse_utc(value):
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return when.astimezone(timezone.utc) if when.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def build(source: dict, *, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    now = now.astimezone(timezone.utc)
    observed = parse_utc(source.get("generated_at")) if isinstance(source, dict) else None
    age = (now - observed).total_seconds() / 3600 if observed else None
    eligible = age is not None and 0 <= age <= MAX_AGE_HOURS
    raw = source.get("candidates") if isinstance(source, dict) else None
    valid_source = (eligible and isinstance(raw, list)
                    and isinstance(source.get("market_rows_seen"), int)
                    and source["market_rows_seen"] >= 100)
    selected = []
    seen = set()
    if valid_source:
        for row in raw[:150]:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            cap, floating = number(row.get("nasdaq_market_cap")), number(row.get("float_shares"))
            price = number(row.get("nasdaq_price"))
            score = number(row.get("structural_score"))
            if (not isinstance(symbol, str) or not TICKER.fullmatch(symbol)
                    or symbol in EXCLUDED or symbol in seen
                    or cap is None or not 0 < cap <= 2_000_000_000
                    or price is None or not 0.1 <= price <= 300
                    or score is None or not 0 <= score <= 100):
                continue
            seen.add(symbol)
            selected.append({
                "symbol": symbol,
                "name": str(row.get("company_name") or symbol)[:110],
                "market_cap_observed": round(cap),
                "float_shares_unverified": round(floating) if floating is not None and floating > 0 else None,
                "structural_score_research": round(score, 1),
                "last_nasdaq_price_observed": None,  # Never republish an old observation as a quote.
                "source_family_market_cap": "nasdaq_screener_research",
                "source_family_float": "yahoo_profile_unofficial",
                "chart_available": False,  # Browser merges published chart availability separately.
                "official_catalyst_verified": False,
                "risk_clearance_verified": False,
                "execution_eligible": False,
            })
            if len(selected) >= MAX_ROWS:
                break
    return {
        "schema": "ghazi.structural_watch.v1",
        "generated_at": now.isoformat(),
        "source_observed_at": observed.isoformat() if observed else None,
        "source_age_hours_at_build": round(age, 2) if age is not None and math.isfinite(age) else None,
        "status": "RESEARCH_SNAPSHOT" if valid_source else "STALE_OR_INVALID",
        "source": "Existing GHAZIBOT Nasdaq research screener and Yahoo profile snapshot",
        "licensing": "Research-only; no raw price redistribution",
        "universe_rows_screened": source.get("market_rows_seen") if valid_source else None,
        "candidates": selected,
        "coverage": {"candidate_rows": len(selected), "has_verified_option_quotes": 0},
        "source_independence": {
            "nasdaq_market_cap_observation": "nonexecution_unofficial_screener",
            "yahoo_profile_float": "unofficial_single_source_not_verified",
        },
        "warnings": [
            "The original source snapshot time is the observation time, not this report's build time",
            "Market cap/float may change; confirm before using a security as a microcap",
            "No issuer catalyst, tradable price, options quote or profitable outcome is certified",
        ],
        "research_only": True,
        "option_execution_ready": False,
        "recommendation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = {}
    if args.source.exists() and args.source.stat().st_size <= MAX_INPUT_BYTES:
        try:
            source = json.loads(args.source.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    payload = build(source, now=datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(f"Structural catalog: {payload['status']} "
          f"rows={payload['coverage']['candidate_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
