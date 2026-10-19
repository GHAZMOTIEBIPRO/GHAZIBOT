"""Private, manual Alpaca Basic probe. Never logs or publishes protected prices."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Minimal standalone import avoids the full trading engine and its large
# dependencies on a manually invoked private market-data probe.
HELPER = Path(__file__).resolve().parents[1] / "options_radar"
if str(HELPER) not in sys.path:
    sys.path.insert(0, str(HELPER))

from alpaca_delayed_research import (
    fetch_completed_daily,
    historical_option_response,
    policy_state,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", default="AAPL")
    parser.add_argument("--option-contract", default="")
    parser.add_argument("--entry-date", default="")
    parser.add_argument("--exit-date", default="")
    args = parser.parse_args()
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    permission = os.getenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED") == "true"
    state = policy_state(api_key=key, secret=secret, internal_use_allowed=permission)
    print("Alpaca private data health:", state["reason"])
    if not state["enabled"]:
        return 0
    now = datetime.now(timezone.utc)
    last = now.date() - timedelta(days=1)
    bars = fetch_completed_daily(
        args.stock, start=last - timedelta(days=6), end=last,
        api_key=key, secret=secret, internal_use_allowed=permission,
        now=now,
    )
    # Metadata only, no source prices, cross-vendor derivatives or keys.
    print("Independent IEX access:",
          "AVAILABLE_INTERNAL_ONLY" if bars.get("bars") else "NOT_VERIFIED",
          "completed_day_count=", len(bars.get("bars", [])))
    if args.option_contract:
        try:
            entry_date = date.fromisoformat(args.entry_date)
            exit_date = date.fromisoformat(args.exit_date)
        except ValueError:
            print("Historical option audit: INVALID_DATES")
            return 0
        if exit_date >= now.date() or (exit_date - entry_date).days > 30:
            print("Historical option audit: INVALID_OR_UNFINISHED_WINDOW")
            return 0
        historic = historical_option_response(
            args.option_contract, entry_date=entry_date, end_date=exit_date,
            api_key=key, secret=secret, internal_use_allowed=permission,
            now=now,
        )
        print("Historical option audit:", historic["status"],
              "trading_execution_verified=false, realized_pnl=unknown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
