"""Run the licensed independent daily-close cross-check (no prices published).

Without two attested, keyed families it writes INSUFFICIENT_LICENSED_SOURCES
and makes no network request.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from options_radar.independent_price_check import eligible_families, run_check

# Per-call pause (seconds) that keeps free-tier rate limits.
PAUSE = {"tiingo": 1.0, "alpaca": 0.5, "twelve_data": 8.0, "polygon": 13.0, "alpha_vantage": 13.0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    families = eligible_families(os.environ)
    if len(families) >= 2:
        from options_radar.market_bars import _call_provider
        from options_radar.settings import Settings

        settings = Settings()

        def fetch(family: str, symbol: str):
            time.sleep(PAUSE.get(family, 1.0))
            return _call_provider(family, settings, symbol, interval="1d",
                                  start=now - timedelta(days=14), end=now, period="1mo").frame

        report = run_check(fetch, families, now=now)
    else:
        report = run_check(lambda family, symbol: None, families, now=now, symbols=())
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Independent price check: status={report['status']} families={families} "
          f"compared={report['symbols_compared']} agreeing={report['symbols_agreeing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
