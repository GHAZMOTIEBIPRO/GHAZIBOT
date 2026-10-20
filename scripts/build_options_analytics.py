"""Publish derived option analytics (expected move, IV, skew, OI, liquidity
screen) for indices and large caps from Cboe's delayed public chains.

Bounded: one request per symbol with a pause between symbols; any failure
is recorded per symbol and never replaced with invented values.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from options_radar.chain_analytics import analyze, fetch_chain
from options_radar.source_permissions import CBOE_BLOCK, cboe_delayed_automation_allowed

SCHEMA = "ghazi.options_analytics.v1"
SYMBOLS = ("SPX", "NDX", "SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "AMD", "MSFT",
           "AMZN", "META", "GOOGL", "AVGO", "MU", "PLTR")


def build(symbols=SYMBOLS, *, fetch=fetch_chain, pause=0.5, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    results, errors = {}, {}
    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(pause)
        try:
            results[symbol] = analyze(symbol, fetch(symbol), now=now)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the rest
            errors[symbol] = type(exc).__name__
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "source": "Cboe delayed public option chains (cdn.cboe.com); derived values only",
        "symbols": results,
        "errors": errors,
        "research_only": True,
        "execution_grade": False,
        "raw_quotes_published": False,
        "data_classes": {"DELAYED_QUOTE": "derived from delayed bid/ask",
                         "PROVIDER_MODEL": "Cboe's own IV/delta, delayed",
                         "HISTORICAL": "open interest from the prior session"},
    }


def blocked_report() -> dict:
    return {
        "schema": SCHEMA,
        "status": CBOE_BLOCK["status"],
        "source": CBOE_BLOCK["source"],
        "reason": CBOE_BLOCK["reason"],
        "reason_ar": CBOE_BLOCK["reason_ar"],
        "symbols": {},
        "errors": {},
        "research_only": True,
        "execution_grade": False,
        "raw_quotes_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not cboe_delayed_automation_allowed():
        # Overwrite any earlier derived file so nothing from Cboe stays published.
        report = {**blocked_report(), "generated_at": datetime.now(timezone.utc).isoformat()}
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Options analytics: SOURCE_TERMS_BLOCKED (no request made).")
        return 0
    report = build()
    ok = sum(1 for r in report["symbols"].values() if r.get("status") == "OK")
    if ok == 0:
        print("Options analytics: no usable chain; previous file kept.")
        return 0
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    print(f"Options analytics: ok={ok} errors={sorted(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
